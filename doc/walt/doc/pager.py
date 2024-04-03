#!/usr/bin/env python
import os
import re
import sys

import commonmark
from walt.doc.color import RE_ESC_COLOR
from walt.doc.color import BOLD_ON, FG_COLOR_DARK_RED, BG_COLOR_WHITE
from walt.doc.markdown import MarkdownRenderer
from walt.common.term import TTYSettings, alternate_screen_buffer

SCROLL_HELP = "<up>/<down>, <page-up>/<page-down>: scroll"
TOPICS_HELP = "<tab>/<shift-tab>, <enter>/<backspace>: browse related topics"
Q_HELP = "<q>: quit"

RE_LINKTAGS = re.compile(r"<L+>")


class Pager:
    QUIT = 0
    SCROLL_UP = 1
    SCROLL_DOWN = 2
    SCROLL_PAGE_UP = 3
    SCROLL_PAGE_DOWN = 4
    SELECT_NEXT_LINK = 5
    SELECT_PREV_LINK = 6
    OPEN_SELECTED_LINK = 7
    RETURN_TO_PREV_MD_CONTENT = 8
    UPDATE_MD_CONTENT_NO_RETURN = 9

    def __init__(self):
        self.tty = TTYSettings()
        self.parser = commonmark.Parser()
        self.renderer = MarkdownRenderer()
        self.error_message = None
        self._scroll_index = 0

    def start_display(self, **env):
        exc = None
        try:
            self.tty.set_raw_no_echo()
            with alternate_screen_buffer(mouse_wheel_as_arrow_keys=True):
                self.pager_main_loop(**env)
        except Exception as e:
            exc = e
        finally:
            self.tty.restore()
            if exc is not None:
                raise exc

    def set_scroll_index(self, value):
        self._scroll_index = value

    def parse_topic_links(self, ast):
        # in order to handle <tab> / <shift>-<tab> navigation we have to
        # know the line number of each link. We do that in 4 steps.
        # 1. replace link literals in the AST, by a tag <LLLL...> of the
        #    same length that we can easily detect later
        walker = ast.walker()
        event = walker.nxt()
        target_topics = []
        saved_info = []
        while event is not None:
            node = event["node"]
            if (
                node.t == "link"
                and event["entering"]
                and node.destination.endswith(".md")
            ):
                saved_info.append((node, node.first_child.literal))
                new_literal = "<" + ("L" * (len(node.first_child.literal) - 2)) + ">"
                node.first_child.literal = new_literal
                target_topics.append(node.destination[:-3])
            event = walker.nxt()
        # 2. render this AST with modified link literals
        text = self.renderer.render(ast, 0)
        # 3. look for the position of our tags in the rendered output
        topic_links = []
        for line_number, line in enumerate(text.splitlines()):
            for link_tag in RE_LINKTAGS.findall(line):
                topic, target_topics = target_topics[0], target_topics[1:]
                topic_links.append((topic, line_number))
        # 4. restore the previous link literals for later reuse of the AST
        for node, literal in saved_info:
            node.first_child.literal = literal
        return topic_links

    def pad_right(self, line):
        return line.ljust(self.tty.cols)

    def format_header(self, **env):
        text = self.get_header_text(cols=self.tty.cols, **env)
        if text == '':
            return 0, ''
        else:
            header_lines = [self.pad_right(line) for line in text.splitlines()]
            header_lines += ["\u2501" * self.tty.cols]
            return len(header_lines), '\r\n'.join(header_lines)

    def footer_line_format(self, footer_line_keys, pad_right=False):
        line = " " + " \u2502 ".join(footer_line_keys)
        if pad_right:
            line = self.pad_right(line) + '\r'
        return line

    def footer_line_short_enough(self, footer_line_keys):
        return len(self.footer_line_format(footer_line_keys)) <= self.tty.cols

    def format_footer(self, num_lines, topic_links, **env):
        sep_line = "\u2501" * self.tty.cols + "\r"
        if self.error_message is None:
            footer_lines = [sep_line]
        else:
            error_line = f"[ {self.error_message} ]".ljust(self.tty.cols)
            esc_start = f'\x1b[{BOLD_ON};{FG_COLOR_DARK_RED};{BG_COLOR_WHITE}m'
            esc_end = '\x1b[0m'
            error_line = f'{esc_start}{error_line}{esc_end}\r'
            footer_lines = [error_line, sep_line]
        footer_static_lines_number = len(footer_lines)
        footer_lines_number = footer_static_lines_number + 1  # first estimation
        while True:
            scrollable = (num_lines > self.tty.rows - footer_lines_number)
            help_keys = self.get_footer_help_keys(
                    topic_links=topic_links,
                    scrollable=scrollable,
                    **env)
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
                    if self.footer_line_short_enough(candidate_footer_line_keys):
                        footer_line_keys = candidate_footer_line_keys
                        help_keys[i] = None  # preserve indices, filter out below
                help_keys = tuple(k for k in help_keys if k is not None)
                line = self.footer_line_format(footer_line_keys, pad_right=True)
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
        if self.error_message is None:
            real_footer_lines_number = footer_lines_number
        else:
            real_footer_lines_number = footer_lines_number -1
        return real_footer_lines_number, footer_lines_number, footer

    def advanced_input(self, prompt, prefill_text=None, completer=None):
        hook_enabled = False
        if prefill_text is not None:
            try:
                import readline
                def hook():
                    readline.insert_text(prefill_text)
                    readline.redisplay()
                readline.set_pre_input_hook(hook)
                hook_enabled = True
            except:
                pass
        completion_enabled = False
        if completer is not None:
            try:
                import readline
                saved_completion = (readline.get_completer_delims(),
                                    readline.get_completer())
                readline.set_completer_delims('')
                readline.set_completer(completer.complete)
                readline.parse_and_bind('tab: complete')
                def no_display(*args, **kwargs):
                    return
                readline.set_completion_display_matches_hook(no_display)
                completion_enabled = True
            except Exception:
                pass
        result = input(prompt)
        # revert
        if hook_enabled:
            readline.set_pre_input_hook()
        if completion_enabled:
            readline.set_completer_delims(saved_completion[0])
            readline.set_completer(saved_completion[1])
        return result

    def prompt_command(self, **kwargs):
        prompt_row_num = self.tty.rows - self.real_footer_height -1
        sys.stdout.write(f"\x1b[H\x1b[{prompt_row_num}B\x1b[K")
        sys.stdout.flush()
        self.tty.restore()
        cmd = self.advanced_input("> ", **kwargs)
        self.tty.set_raw_no_echo()
        return cmd

    def pager_main_loop(self, **env):
        # activate the pager
        should_load_topic, should_render_markdown, should_redraw = True, True, True
        while True:
            if should_load_topic:
                selected_link_num = 0
                content, self._scroll_index = self.get_md_content(
                        rows=self.tty.rows, **env)
                ast = self.parser.parse(content)
                topic_links = self.parse_topic_links(ast)
                should_load_topic = False
            if should_render_markdown:
                text = self.renderer.render(ast, selected_link_num)
                lines = text.split("\n")
                # we have to behave the same wether the document ends with an empty line
                # (color escape codes excluded) or not
                last_line_without_color = "".join(RE_ESC_COLOR.split(lines[-1]))
                if len(last_line_without_color) == 0:
                    lines = lines[:-1]  # remove last line
                num_lines = len(lines)
                # adapt footer help
                header_height, header = self.format_header(**env)
                real_footer_height, footer_height, footer = self.format_footer(
                    num_lines=num_lines,
                    topic_links=topic_links,
                    **env
                )
                page_height = self.tty.rows - (footer_height + header_height)
                self.real_footer_height = real_footer_height  # save
                should_render_markdown = False
            if should_redraw:
                # ensure the text after the index is long enough to fill the
                # pager screen
                if len(lines) < self._scroll_index + page_height:
                    lines += [" " * self.tty.cols] * (
                            self._scroll_index + page_height - len(lines))
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
                hidden_lines = lines[:self._scroll_index]
                sys.stdout.write("\r".join(hidden_lines) + "\r")
                displayed = lines[self._scroll_index : self._scroll_index + page_height]
                sys.stdout.write("\r\n".join(displayed) + "\r\n\x1b[0m")
                sys.stdout.write(footer)
                should_redraw = False
            # process keyboard input
            next_index = self._scroll_index
            next_selected_link_num = selected_link_num
            # get keyboard input
            action = None
            while action is None:
                req = sys.stdin.read(1)
                action = self.handle_keypress(req, **env)
            if action == Pager.QUIT:
                return False  # should not continue
            elif action == Pager.RETURN_TO_PREV_MD_CONTENT:
                return True  # return from the recursive call
            elif action in (Pager.SCROLL_UP, Pager.SCROLL_DOWN,
                            Pager.SCROLL_PAGE_UP, Pager.SCROLL_PAGE_DOWN):
                next_index = self._scroll_index + {
                        Pager.SCROLL_UP: -1,
                        Pager.SCROLL_DOWN: 1,
                        Pager.SCROLL_PAGE_UP: -page_height,
                        Pager.SCROLL_PAGE_DOWN: page_height,
                }[action]
            elif action in (Pager.SELECT_NEXT_LINK, Pager.SELECT_PREV_LINK):
                if len(topic_links) == 0:
                    continue  # ignore the keypress
                link_inc, repositioning_offset = {
                        Pager.SELECT_NEXT_LINK: (1, -page_height + 2),
                        Pager.SELECT_PREV_LINK: (-1, -2),
                }[action]
                next_selected_link_num = (selected_link_num + link_inc) % (
                                            len(topic_links))
                # ensure the viewport includes the selected link
                selected_link_line = topic_links[next_selected_link_num][1]
                if (
                    self._scroll_index + 2 > selected_link_line
                    or self._scroll_index < selected_link_line - page_height + 2
                ):
                    # reposition the viewport to include the selected link
                    next_index = selected_link_line + repositioning_offset
            elif action == Pager.OPEN_SELECTED_LINK:
                selected_topic, selected_link_line = topic_links[selected_link_num]
                if (
                    self._scroll_index > selected_link_line
                    or self._scroll_index < selected_link_line - page_height
                ):
                    # link is not visible, user probably did not want to jump to it
                    continue  # ignore the keypress
                # recursive call
                should_continue = self.select_topic(selected_topic, **env)
                if should_continue:
                    # we are returning from a recursive call to a selected topic page,
                    # we now have to redraw the screen
                    should_redraw = True
                    continue
                else:
                    # we should quit
                    return False
            elif action == Pager.UPDATE_MD_CONTENT_NO_RETURN:
                should_load_topic = True
                should_render_markdown = True
                should_redraw = True
                continue
            # limit index value to fit the viewport
            next_index = min(next_index, num_lines - (page_height - 10))
            next_index = max(next_index, 0)
            if next_selected_link_num != selected_link_num:
                should_render_markdown = True
                should_redraw = True
            if next_index != self._scroll_index:
                should_redraw = True
            self._scroll_index = next_index
            selected_link_num = next_selected_link_num


class DocPager(Pager):
    def __init__(self, get_md_content):
        super().__init__()
        self._get_md_content = get_md_content

    def display_topic(self, topic):
        content = self._get_md_content(topic, err_out=True)
        if content is None:
            return
        if os.isatty(sys.stdout.fileno()):
            self.start_display(
                    topic=topic,
                    depth=0
            )
        else:
            print(content)
            # For debugging colors with hexdump, prefer:
            # print(MarkdownRenderer().render(content))

    def get_header_text(self, **env):
        return ""  # no header

    def get_footer_help_keys(self, topic_links, scrollable, depth, **env):
        help_keys = []
        if scrollable:
            help_keys += [SCROLL_HELP]
        if len(topic_links) > 0 or depth > 0:
            help_keys += [TOPICS_HELP]
        help_keys += [Q_HELP]
        return help_keys

    def get_md_content(self, topic, **env):
        return self._get_md_content(topic), 0

    def select_topic(self, selected_topic, depth, **env):
        # recursive call to the pager main loop
        return self.pager_main_loop(topic=selected_topic, depth=depth + 1)

    def handle_keypress(self, req, depth, **env):
        if req == "q":
            return Pager.QUIT
        elif req == "\x7f":  # backspace (return to prev topic)
            if depth > 0:
                return Pager.RETURN_TO_PREV_MD_CONTENT
        elif req == "A":  # up   (we get '\e[A', but '\e' and '[' are ignored)
            return Pager.SCROLL_UP
        elif req == "B":  # down
            return Pager.SCROLL_DOWN
        elif req == "5":  # up
            return Pager.SCROLL_PAGE_UP
        elif req == "6":  # down
            return Pager.SCROLL_PAGE_DOWN
        elif req == "\t":  # tab
            return Pager.SELECT_NEXT_LINK
        elif req == "Z":  # shift-tab
            return Pager.SELECT_PREV_LINK
        elif req == "\r":  # <enter>: open selected topic
            return Pager.OPEN_SELECTED_LINK
