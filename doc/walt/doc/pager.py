#!/usr/bin/env python
"""Interactive terminal pager displaying markdown content.

Subclass `Pager` and implement `get_page()`, returning a `Page` with either
markdown content (requires the commonmark module) or text already formatted
for the terminal (with ANSI escape codes). Optionally override
`on_key()`, `resolve_link()`, `get_help_keys()`, `format_url()` and
`diagram_fallback_message()`. Then call `run(location)`.

A "location" is an opaque object identifying what is displayed (e.g.,
a help topic name). The pager keeps a stack of locations: opening a
link pushes a new one, <backspace> returns to the previous one.
"""
import os
import re
import select
import sys
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from walt.doc.color import RE_ESC_COLOR
from walt.doc.color import BOLD_ON, FG_COLOR_DARK_RED, BG_COLOR_WHITE
from walt.common.term import (
        TTYSettings,
        alternate_screen_buffer,
        wait_for_large_enough_terminal,
        on_sigwinch_raise_exception,
        SIGWINCHException,
)

SCROLL_HELP = "<up>/<down>, <page-up>/<page-down>: scroll"
LINKS_HELP = "<tab>/<shift-tab>, <enter>/<backspace>: browse links"
Q_HELP = "<q>: quit"

# escape sequences which do not occupy screen space
RE_ESC_CSI = re.compile("\x1b" + r"\[[0-9;?]*[A-Za-z]")

# if we have something larger than current window size to display,
# we may ask the user to resize it.
# however, if our text width is really large, don't block usage
# because the user may just have a small screen.
REASONABLE_MIN_SCREEN_WIDTH = 100

# max delay between the bytes of an escape sequence
ESC_SEQ_TIMEOUT = 0.05

# escape sequences (without the leading ESC) -> key names
ESC_SEQUENCES = {
    "[A": "up",
    "[B": "down",
    "[C": "right",
    "[D": "left",
    "OA": "up",
    "OB": "down",
    "OC": "right",
    "OD": "left",
    "[5~": "page-up",
    "[6~": "page-down",
    "[H": "home",
    "[F": "end",
    "[1~": "home",
    "[4~": "end",
    "[Z": "shift-tab",
}

SINGLE_BYTE_KEYS = {
    "\t": "tab",
    "\r": "enter",
    "\n": "enter",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\x1b": "escape",
}


class Action(Enum):
    QUIT = auto()
    SCROLL_UP = auto()
    SCROLL_DOWN = auto()
    PAGE_UP = auto()
    PAGE_DOWN = auto()
    NEXT_LINK = auto()
    PREV_LINK = auto()
    OPEN_LINK = auto()
    BACK = auto()
    RELOAD = auto()
    IGNORE = auto()


DEFAULT_BINDINGS = {
    "q": Action.QUIT,
    "up": Action.SCROLL_UP,
    "down": Action.SCROLL_DOWN,
    "page-up": Action.PAGE_UP,
    "page-down": Action.PAGE_DOWN,
    "tab": Action.NEXT_LINK,
    "shift-tab": Action.PREV_LINK,
    "enter": Action.OPEN_LINK,
    "backspace": Action.BACK,
}


@dataclass
class Page:
    # content: either markdown, or text formatted for the terminal
    markdown: Optional[str] = None
    text: Optional[str] = None
    header: str = ""                # displayed above the content
    scroll: Optional[int] = None    # None: keep the current scroll position

    def __post_init__(self):
        if (self.markdown is None) == (self.text is None):
            raise ValueError("Page needs either markdown or text content.")


class TextContent:
    """Text already formatted for the terminal; it has no links."""
    links = ()

    def __init__(self, text):
        # clear each screen line ("\x1b[K") before writing it: unlike
        # markdown rendering, the text may not span the whole terminal width.
        # (clearing at the start, not at the end, allows a line to end with
        # its own "\x1b[K" to fill the rest of the line with a background
        # color, as render_code() does.)
        self.text = "\n".join("\x1b[K" + line for line in text.split("\n"))
        self.max_width = max(
            (len(RE_ESC_CSI.sub("", line)) for line in text.split("\n")),
            default=0)

    def render(self, selected_link_num):
        return self.text, self.max_width


@dataclass
class _StackEntry:
    location: object
    scroll_index: int = 0
    selected_link_num: int = 0


def _read_byte(fd, timeout=None):
    if timeout is not None:
        ready, _, _ = select.select([fd], [], [], timeout)
        if len(ready) == 0:
            return None
    b = os.read(fd, 1)
    if len(b) == 0:
        raise EOFError()
    return b[0]


def read_key(fd):
    """Read one keypress from fd (in raw mode) and return its name.

    Returns a name such as "up", "page-down", "tab", "enter", "backspace",
    a single printable character, or None for an unknown escape sequence.
    """
    b = _read_byte(fd)
    if b == 0x1b:
        seq = ""
        while True:
            nb = _read_byte(fd, ESC_SEQ_TIMEOUT)
            if nb is None:
                break
            c = chr(nb)
            seq += c
            if len(seq) == 1:
                if c not in "[O":
                    break   # not a CSI or SS3 sequence
            elif c.isalpha() or c == "~":
                break   # final byte
        if seq == "":
            return "escape"
        return ESC_SEQUENCES.get(seq)
    if b >= 0xc0:
        # utf-8 multi-byte character
        num_bytes = 2 if b < 0xe0 else 3 if b < 0xf0 else 4
        data = bytes([b] + [_read_byte(fd) for _ in range(num_bytes - 1)])
        return data.decode("utf-8", errors="replace")
    c = chr(b)
    return SINGLE_BYTE_KEYS.get(c, c)


class Pager:

    def __init__(self, min_width=REASONABLE_MIN_SCREEN_WIDTH):
        # min_width: if the rendered content is wider than the terminal
        # (and not wider than min_width), ask the user to resize it.
        self.tty = TTYSettings()
        self.min_width = min_width
        self._md_renderer = None
        self._error_message = None
        self._stack = []
        self.real_footer_height = 0

    # --- hooks for subclasses -------------------------------------------

    def get_page(self, location, rows, cols):
        """Return the Page to display at `location`."""
        raise NotImplementedError

    def on_key(self, key):
        """Handle a keypress; see read_key() for key names.

        Return an Action, or None to apply the default key bindings.
        """
        return None

    def resolve_link(self, destination):
        """Return the location a link points to, or None if the link
        should not be navigable from the pager (default)."""
        return None

    def get_help_keys(self, scrollable, has_links, can_go_back):
        """Return the list of help strings displayed in the footer."""
        help_keys = []
        if scrollable:
            help_keys += [SCROLL_HELP]
        if has_links or can_go_back:
            help_keys += [LINKS_HELP]
        help_keys += [Q_HELP]
        return help_keys

    def format_url(self, url):
        """Format the URL of a non-navigable link for display."""
        return url

    def diagram_fallback_message(self, location):
        """Message displayed when a diagram cannot be rendered in the
        terminal, or None for the default message."""
        return None

    # --- services for subclasses ----------------------------------------

    @property
    def location(self):
        return self._stack[-1].location

    @property
    def scroll_index(self):
        return self._stack[-1].scroll_index

    @scroll_index.setter
    def scroll_index(self, value):
        self._stack[-1].scroll_index = value

    def show_error(self, msg):
        """Display an error message until the next keypress."""
        self._error_message = msg

    def has_error(self):
        return self._error_message is not None

    def prompt(self, prefill=None, completer=None):
        """Prompt the user for a command line at the bottom of the screen.

        completer: readline-style function completer(text, state).
        """
        prompt_row_num = self.tty.rows - self.real_footer_height - 1
        sys.stdout.write(f"\x1b[H\x1b[{prompt_row_num}B\x1b[K")
        sys.stdout.flush()
        self.tty.restore()
        try:
            return self._advanced_input("> ", prefill, completer)
        finally:
            self.tty.set_raw_no_echo()

    # --- entry point ----------------------------------------------------

    def run(self, location=None):
        self._stack = [_StackEntry(location)]
        exc = None
        try:
            self.tty.set_raw_no_echo()
            with alternate_screen_buffer(mouse_wheel_as_arrow_keys=True):
                self._main_loop()
        except Exception as e:
            exc = e
        finally:
            self.tty.restore()
            if exc is not None:
                raise exc

    # --- internals ------------------------------------------------------

    def _is_nav_link(self, destination):
        return self.resolve_link(destination) is not None

    def _get_content(self, page, location):
        if page.text is not None:
            return TextContent(page.text)
        # markdown modules are only loaded when needed
        from walt.doc.markdown import MarkdownContent, MarkdownRenderer
        if self._md_renderer is None:
            self._md_renderer = MarkdownRenderer(
                    min_width=self.min_width,
                    is_nav_link=self._is_nav_link,
                    format_url=self.format_url,
                    diagram_fallback=self.diagram_fallback_message,
            )
        return MarkdownContent(self._md_renderer, page.markdown,
                               self.resolve_link, location)

    def _advanced_input(self, prompt, prefill_text=None, completer=None):
        hook_enabled = False
        if prefill_text is not None:
            try:
                import readline
                def hook():
                    readline.insert_text(prefill_text)
                    readline.redisplay()
                readline.set_pre_input_hook(hook)
                hook_enabled = True
            except Exception:
                pass
        completion_enabled = False
        if completer is not None:
            try:
                import readline
                saved_completion = (readline.get_completer_delims(),
                                    readline.get_completer())
                readline.set_completer_delims('')
                readline.set_completer(completer)
                readline.parse_and_bind('tab: complete')
                def no_display(*args, **kwargs):
                    return
                readline.set_completion_display_matches_hook(no_display)
                completion_enabled = True
            except Exception:
                pass
        try:
            return input(prompt)
        finally:
            # revert
            if hook_enabled:
                readline.set_pre_input_hook()
            if completion_enabled:
                readline.set_completer_delims(saved_completion[0])
                readline.set_completer(saved_completion[1])

    def _pad_right(self, line):
        return line.ljust(self.tty.cols)

    def _format_header(self, text):
        if text == '':
            return 0, ''
        else:
            header_lines = [self._pad_right(line) for line in text.splitlines()]
            header_lines += ["━" * self.tty.cols]
            return len(header_lines), '\r\n'.join(header_lines)

    def _footer_line_format(self, footer_line_keys, pad_right=False):
        line = " " + " │ ".join(footer_line_keys)
        if pad_right:
            line = self._pad_right(line) + '\r'
        return line

    def _footer_line_short_enough(self, footer_line_keys):
        return len(self._footer_line_format(footer_line_keys)) <= self.tty.cols

    def _format_footer(self, num_lines, has_links):
        sep_line = "━" * self.tty.cols + "\r"
        if self._error_message is None:
            footer_lines = [sep_line]
        else:
            error_line = f"[ {self._error_message} ]".ljust(self.tty.cols)
            esc_start = f'\x1b[{BOLD_ON};{FG_COLOR_DARK_RED};{BG_COLOR_WHITE}m'
            esc_end = '\x1b[0m'
            error_line = f'{esc_start}{error_line}{esc_end}\r'
            footer_lines = [error_line, sep_line]
        footer_static_lines_number = len(footer_lines)
        footer_lines_number = footer_static_lines_number + 1  # first estimation
        while True:
            scrollable = (num_lines > self.tty.rows - footer_lines_number)
            help_keys = self.get_help_keys(
                    scrollable=scrollable,
                    has_links=has_links,
                    can_go_back=len(self._stack) > 1)
            # sort help keys by decreasing length
            help_keys = sorted(help_keys,
                               key=(lambda k: len(k)),
                               reverse=True)
            # arrange help keys on as few lines as possible
            footer_lines = footer_lines[:footer_static_lines_number]
            while len(help_keys) > 0:
                footer_line_keys, help_keys = (help_keys[0],), list(help_keys[1:])
                for i, candidate_key in tuple(enumerate(help_keys)):
                    candidate_footer_line_keys = footer_line_keys + (candidate_key,)
                    if self._footer_line_short_enough(candidate_footer_line_keys):
                        footer_line_keys = candidate_footer_line_keys
                        help_keys[i] = None  # preserve indices, filter out below
                help_keys = tuple(k for k in help_keys if k is not None)
                line = self._footer_line_format(footer_line_keys, pad_right=True)
                footer_lines += [line]
            footer_lines_number = len(footer_lines)
            if (
                    scrollable is False and
                    num_lines > self.tty.rows - footer_lines_number
               ):
                # our estimation of number of footer lines was wrong, and it appears
                # that the text zone would actually be scrollable, let's restart
                continue
            else:
                break  # ok proceed
        footer = "\n".join(footer_lines)
        if self._error_message is None:
            real_footer_lines_number = footer_lines_number
        else:
            real_footer_lines_number = footer_lines_number -1
        return real_footer_lines_number, footer_lines_number, footer

    def _get_action(self, key):
        if key is None:
            return Action.IGNORE
        self._error_message = None
        action = self.on_key(key)
        if action is None:
            action = DEFAULT_BINDINGS.get(key, Action.IGNORE)
        return action

    def _main_loop(self):
        should_load, should_render, should_redraw = True, True, True
        restoring = False   # True when returning to a previous location
        while True:
            entry = self._stack[-1]
            if should_load:
                page = self.get_page(entry.location,
                                     rows=self.tty.rows, cols=self.tty.cols)
                if restoring:
                    restoring = False   # keep saved scroll and link selection
                else:
                    entry.selected_link_num = 0
                    if page.scroll is not None:
                        entry.scroll_index = page.scroll
                content = self._get_content(page, entry.location)
                links = content.links
                if entry.selected_link_num >= len(links):
                    entry.selected_link_num = 0
                should_load = False
            if should_render:
                text, max_width = content.render(entry.selected_link_num)
                if max_width <= self.min_width:
                    if wait_for_large_enough_terminal(max_width):
                        # terminal resized, render again
                        text, max_width = content.render(
                                entry.selected_link_num)
                lines = text.split("\n")
                # we have to behave the same wether the document ends with an empty line
                # (color escape codes excluded) or not
                last_line_without_color = "".join(RE_ESC_COLOR.split(lines[-1]))
                if len(last_line_without_color) == 0:
                    lines = lines[:-1]  # remove last line
                num_lines = len(lines)
                # adapt footer help
                header_height, header = self._format_header(page.header)
                real_footer_height, footer_height, footer = self._format_footer(
                    num_lines=num_lines,
                    has_links=len(links) > 0,
                )
                page_height = self.tty.rows - (footer_height + header_height)
                self.real_footer_height = real_footer_height  # save
                should_render = False
            if should_redraw:
                # ensure the text after the index is long enough to fill the
                # pager screen
                if len(lines) < entry.scroll_index + page_height:
                    lines += [" " * self.tty.cols] * (
                            entry.scroll_index + page_height - len(lines))
                # to avoid the terminal scrolls, we restart the drawing at
                # the top-left corner.
                sys.stdout.write("\x1b[H")
                if header_height > 0:
                    sys.stdout.write(header + '\r\n')
                # the lines displayed are actually in range
                # [index:index+page_height], but if one of the previous
                # lines entered a 'bold' zone for example, (esc code '\e[1m'
                # and no '\e[21m' code yet to revert it), we should start
                # the first line with this context. That's why we paste the
                # whole document up to index+page_height, including the
                # lines before the view position.  For optimization, we
                # print these lines on the same tty line, so one line erases
                # the previous one.
                hidden_lines = lines[:entry.scroll_index]
                sys.stdout.write("\r".join(hidden_lines) + "\r")
                displayed = lines[entry.scroll_index : entry.scroll_index + page_height]
                sys.stdout.write("\r\n".join(displayed) + "\r\n\x1b[0m")
                sys.stdout.write(footer)
                sys.stdout.flush()
                should_redraw = False
            # get keyboard input
            prev_error_message = self._error_message
            try:
                with on_sigwinch_raise_exception():
                    key = read_key(sys.stdin.fileno())
                action = self._get_action(key)
            except SIGWINCHException:
                # window size change, refresh
                action = Action.RELOAD
            if action == Action.IGNORE:
                if self._error_message != prev_error_message:
                    should_render, should_redraw = True, True
                continue
            # process the action
            next_index = entry.scroll_index
            next_selected_link_num = entry.selected_link_num
            if action == Action.QUIT:
                return
            elif action == Action.BACK:
                if len(self._stack) > 1:
                    self._stack.pop()
                    should_load, should_render, should_redraw = True, True, True
                    restoring = True
                continue
            elif action == Action.RELOAD:
                should_load, should_render, should_redraw = True, True, True
                continue
            elif action in (Action.SCROLL_UP, Action.SCROLL_DOWN,
                            Action.PAGE_UP, Action.PAGE_DOWN):
                next_index = entry.scroll_index + {
                        Action.SCROLL_UP: -1,
                        Action.SCROLL_DOWN: 1,
                        Action.PAGE_UP: -page_height,
                        Action.PAGE_DOWN: page_height,
                }[action]
            elif action in (Action.NEXT_LINK, Action.PREV_LINK):
                if len(links) > 0:
                    link_inc, repositioning_offset = {
                            Action.NEXT_LINK: (1, -page_height + 2),
                            Action.PREV_LINK: (-1, -2),
                    }[action]
                    next_selected_link_num = (
                            entry.selected_link_num + link_inc) % len(links)
                    # ensure the viewport includes the selected link
                    selected_link_line = links[next_selected_link_num][1]
                    if (
                        entry.scroll_index + 2 > selected_link_line
                        or entry.scroll_index < selected_link_line - page_height + 2
                    ):
                        # reposition the viewport to include the selected link
                        next_index = selected_link_line + repositioning_offset
            elif action == Action.OPEN_LINK:
                if entry.selected_link_num < len(links):
                    target, selected_link_line = links[entry.selected_link_num]
                    if not (
                        entry.scroll_index > selected_link_line
                        or entry.scroll_index < selected_link_line - page_height
                    ):
                        # link is visible, open it
                        self._stack.append(_StackEntry(target))
                        should_load, should_render, should_redraw = True, True, True
                        continue
                    # otherwise, the user probably did not want to jump to it
            # limit index value to fit the viewport
            next_index = min(next_index, num_lines - (page_height - 10))
            next_index = max(next_index, 0)
            if next_selected_link_num != entry.selected_link_num:
                should_render = True
                should_redraw = True
            if next_index != entry.scroll_index:
                should_redraw = True
            if self._error_message != prev_error_message:
                should_render = True
                should_redraw = True
            entry.scroll_index = next_index
            entry.selected_link_num = next_selected_link_num
