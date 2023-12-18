#!/usr/bin/env python
import termios
import textwrap

from pygments import highlight
from pygments.formatters import Terminal256Formatter
from pygments.lexers import get_lexer_by_name
from walt.doc.color import (
    BG_COLOR_DEFAULT,
    BG_COLOR_LIGHT_GREY,
    BG_COLOR_WHITE,
    FG_COLOR_BLACK,
    FG_COLOR_BLUE,
    FG_COLOR_DEFAULT,
    FG_COLOR_DARK_RED,
    RE_ESC_COLOR,
    FormatState,
    get_transition_esc_sequence,
    optimize_and_reset_default_colors
)
from walt.doc.mdtable import detect_table, render_table
from walt.common.term import TTYSettings

MAX_TARGET_WIDTH = 120

FG_COLOR_MARKDOWN = FG_COLOR_BLACK
BG_COLOR_MARKDOWN = BG_COLOR_WHITE
FG_COLOR_SOURCE_CODE = FG_COLOR_BLACK
BG_COLOR_SOURCE_CODE = BG_COLOR_LIGHT_GREY
BG_COLOR_SOURCE_CODE_HIGHLIGHT = "103"
FG_COLOR_URL = FG_COLOR_BLUE
FG_COLOR_HEADING = FG_COLOR_DARK_RED


class MarkdownRenderer:
    def __init__(self, *args, **kwargs):
        self.list_numbering = []
        # initialize context with current terminal setup (default for all attrs)
        init_state = FormatState(
            bg_color=BG_COLOR_DEFAULT,
            fg_color=FG_COLOR_DEFAULT,
            underline=False,
            bold=False,
            dim=False,
        )
        self.contexts = [init_state]
        try:
            tty = TTYSettings()
            self.target_width = min(tty.cols, MAX_TARGET_WIDTH)
        except termios.error:
            # Stdout seems not to be a terminal
            self.target_width = 80  # Minimal requirement

    def render(self, ast, selected_link_num):
        self.link_num = 0
        self.selected_link_num = selected_link_num
        walker = ast.walker()
        self.buf = ""
        event = walker.nxt()
        while event is not None:
            type_ = event["node"].t
            if not hasattr(self, type_):
                raise NotImplementedError(type_)
            getattr(self, type_)(event["node"], event["entering"])
            event = walker.nxt()
        optimized_buf = optimize_and_reset_default_colors(
                self.buf, FG_COLOR_DEFAULT, BG_COLOR_DEFAULT
        )
        return optimized_buf

    def document(self, node, entering):
        if entering:
            self.stack_context(fg_color=FG_COLOR_MARKDOWN, bg_color=BG_COLOR_MARKDOWN)
        else:
            # markdown background color should span to right edge
            self.buf = self.buf.replace("\n", "\033[K\n")
            self.pop_context()

    def lit(self, s, reset=False):
        if reset:
            self.buf = ""
        self.buf += s

    def text(self, node, entering=None):
        self.lit(node.literal)

    def stack_context(self, **kwargs):
        curr_state = self.contexts[-1]
        new_state = curr_state.alter(**kwargs)
        self.lit(get_transition_esc_sequence(curr_state, new_state))
        self.contexts.append(new_state)

    def pop_context(self):
        curr_state = self.contexts[-1]
        new_state = self.contexts[-2]
        self.lit(get_transition_esc_sequence(curr_state, new_state))
        self.contexts = self.contexts[:-1]

    def cr(self):
        self.lit("\n")

    def softbreak(self, node=None, entering=None):
        self.cr()

    def linebreak(self, node=None, entering=None):
        self.cr()

    def html_inline(self, node, entering):
        self.lit(node.literal)

    def link(self, node, entering):
        if node.destination.endswith(".md"):
            if entering:
                if self.link_num == self.selected_link_num:
                    self.stack_context(bold=True, underline=True)
            else:
                if self.link_num == self.selected_link_num:
                    self.pop_context()
                self.link_num += 1
        else:
            if not entering:
                # replace [<text>](<url>) -> <text> (<url>)
                self.lit(" (")
                self.stack_context(fg_color=FG_COLOR_URL)
                self.lit(node.destination)
                self.pop_context()
                self.lit(")")

    def paragraph(self, node, entering):
        if entering:
            node.saved_buf = self.buf
            self.buf = ""
        else:
            if detect_table(self.buf):
                table_buf = self.buf
                self.lit(node.saved_buf, reset=True)
                render_table(self, table_buf)
            else:
                escaped = self.wrap_escaped(self.buf)
                self.lit(node.saved_buf + escaped, reset=True)
            self.cr()
            self.cr()

    def block_quote(self, node, entering):
        if entering:
            node.saved_buf = self.buf
            self.target_width -= 2
            self.buf = ""
        else:
            self.buf = node.saved_buf + self.quoted(self.buf)
            self.target_width += 2
            self.cr()

    def justify(self, words, num_spaces):
        num_intervals = len(words) - 1
        if num_intervals == 0:
            # only one word, cannot justify
            return words[0]
        # Fill intervals evenly with appropriate number of spaces
        added_spaces = [" " * (num_spaces // num_intervals)] * num_intervals
        num_spaces -= (num_spaces // num_intervals) * num_intervals
        # Because of the integer division, a few remaining spaces should be added
        # (less than the number of intervals).
        # Preferably add one more space after ponctuation marks.
        for signs in (".!?", ":;", ","):
            for i, word in enumerate(words[:-1]):
                if num_spaces == 0:
                    break
                if word[-1] in signs:
                    added_spaces[i] += " "
                    num_spaces -= 1
        # For better understanding of what we will do with any space still remaining,
        # let's take an example:
        # if we have 15 intervals and 4 remaining spaces, distribute evenly
        # these 4 spaces at intervals 1*15/5=3, 2*15/5=6, 3*15/5=9 and 4*15/5=12.
        for i in range(1, num_spaces + 1):
            added_spaces[i * num_intervals // (num_spaces + 1)] += " "
        # add a fake ending 'interval' for the zip() function below
        added_spaces += [""]
        return "".join((word + spacing) for word, spacing in zip(words, added_spaces))

    def real_text_len(self, text):
        return len("".join(RE_ESC_COLOR.split(text)))

    def wrap_escaped(self, text):
        # textwrap.fill does not work well because of the escape sequences
        wrapped_lines = []
        curr_words = []
        curr_words_no_color = []
        for line in text.split("\n"):
            for word in line.split(" "):
                word_no_color = "".join(RE_ESC_COLOR.split(word))
                min_line_no_color = " ".join(curr_words_no_color + [word_no_color])
                min_len = len(min_line_no_color)
                if 1 + min_len > self.target_width:
                    # cannot include the new word, format previous ones into a line
                    len_no_space = len("".join(curr_words_no_color))
                    num_spaces = self.target_width - 1 - len_no_space
                    curr_line = self.justify(curr_words, num_spaces)
                    wrapped_lines.append(" " + curr_line)
                    # the new word will be included into next line
                    curr_words = [word]
                    curr_words_no_color = [word_no_color]
                else:
                    # ok, include this new word into the current line
                    curr_words.append(word)
                    curr_words_no_color.append(word_no_color)
            wrapped_lines.append(" " + " ".join(curr_words))
            curr_words, curr_words_no_color = [], []
        # after wrapping is validated, we can revert non-breaking spaces
        # to regular space.
        return "\n".join(wrapped_lines).replace("\xa0", " ")

    def quoted(self, text):
        return (
            "\n".join((" \u2588" + line) for line in text.rstrip("\n").split("\n"))
            + "\n"
        )

    def heading(self, node, entering):
        if entering:
            level = 1 if node.level is None else node.level
            self.cr()
            self.stack_context(fg_color=FG_COLOR_HEADING, bold=True)
            self.lit("#" * level + " ")
            self.underline(None, True)
        else:
            self.underline(None, False)
            self.pop_context()
            self.cr()
            self.cr()

    def underline(self, node, entering):
        if entering:
            self.stack_context(underline=True)
        else:
            self.pop_context()

    def strong(self, node, entering):
        if entering:
            self.stack_context(bold=True)
        else:
            self.pop_context()

    def emph(self, node, entering):
        if entering:
            self.stack_context(dim=True)
        else:
            self.pop_context()

    def code(self, node, entering):
        self.stack_context(fg_color=FG_COLOR_SOURCE_CODE, bg_color=BG_COLOR_SOURCE_CODE)
        # replace spaces with non-breaking space
        # (this should be reverted after the paragraph has been wrapped, see above)
        self.lit(node.literal.replace(" ", "\xa0"))
        self.pop_context()

    def pre_format_code_block(self, text):
        text = textwrap.dedent(text)
        text = "\n".join(line.rstrip() for line in text.rstrip("\n").split("\n"))
        return text

    def add_line_prefix(self, lineno, line, breakpoints, line_number_width):
        elements = ()
        if breakpoints is not None:
            elements += ("\u2BC3" if lineno in breakpoints else " ",)
        if line_number_width is not None:
            elements += (f"{lineno:>{line_number_width}}",)
        if len(elements) > 0:
            elements += ("|",)
        elements += (line,)
        return " ".join(elements)

    def add_line_prefixes(self, lines, breakpoints, line_number_width):
        return [self.add_line_prefix(n+1, line, breakpoints, line_number_width)
                for n, line in enumerate(lines)]

    def code_block(self, node, entering):
        code_text = self.pre_format_code_block(node.literal)
        colored_text = code_text  # if we cannot perform syntax highlighting
        params = {}
        enable_linenos = False
        if node.info != '':
            language = None
            for spec in node.info.split():
                if '=' in spec:
                    param, value = spec.split("=")
                    params[param] = value
                elif spec == "linenos":
                    enable_linenos = True
                else:
                    language = spec
            if language is not None:
                try:
                    lexer = get_lexer_by_name(language)
                    colored_text = highlight(code_text, lexer, Terminal256Formatter())
                    colored_text = colored_text.rstrip("\n")
                except Exception:  # syntax highlighting failed: just use the raw code
                    colored_text = code_text
        highlight_line = params.get("highlight-line", None)
        breakpoints = params.get("breakpoints", None)
        if breakpoints is not None:
            if breakpoints == '':
                breakpoints = ()
            else:
                breakpoints = set(int(line) for line in breakpoints.split(","))
        code_lines = code_text.split("\n")
        if enable_linenos:
            line_number_width = len(str(len(code_lines)))
        else:
            line_number_width = None
        code_lines = self.add_line_prefixes(
                code_lines, breakpoints, line_number_width)
        colored_lines = colored_text.split("\n")
        colored_lines = self.add_line_prefixes(
                colored_lines, breakpoints, line_number_width)
        if highlight_line is not None:
            highlight_line = int(highlight_line) - 1  # 1-indexing -> 0-indexing
            sections = (
                (0, highlight_line, BG_COLOR_SOURCE_CODE),
                (highlight_line, highlight_line+1, BG_COLOR_SOURCE_CODE_HIGHLIGHT),
                (highlight_line+1, len(code_lines), BG_COLOR_SOURCE_CODE),
            )
        else:
            sections = (
                (0, len(code_lines), BG_COLOR_SOURCE_CODE),
            )
        code_width = max(len(line) for line in code_text.split("\n")) + 1
        code_width = max(code_width, self.target_width)
        for section_start, section_end, bg_color in sections:
            section_code_lines = code_lines[section_start:section_end]
            section_colored_lines = colored_lines[section_start:section_end]
            if len(section_code_lines) == 0:
                continue  # empty section, e.g., when highlighting 1st line
            # pygments output includes escape codes to reset the foreground
            # or background color, we have to make a pass to revert those escape
            # codes and get the default colors we want.
            section_colored_text = optimize_and_reset_default_colors(
                "\n".join(section_colored_lines),
                FG_COLOR_SOURCE_CODE,
                bg_color
            )
            section_code_text = "\n".join(section_code_lines)
            for code_line, colored_line in zip(
                section_code_text.split("\n"), section_colored_text.split("\n")
            ):
                self.stack_context(
                    fg_color=FG_COLOR_SOURCE_CODE, bg_color=bg_color
                )
                # paste the colored line, then kill ('\e[K') in order to paint the
                # rest with background color of source code, then move to the right
                # ('\e[<N>C') up to the edge of code block
                self.lit(colored_line + "\x1b[K\x1b[%dC" %
                         (code_width - len(code_line)))
                # this will restore markdown background color
                self.pop_context()
                # line feed
                self.cr()
        self.cr()

    def list(self, node, entering):
        if entering:
            if node.list_data["type"] == "bullet":
                self.list_numbering.append(None)
            else:
                self.list_numbering.append(1)
        else:
            self.list_numbering = self.list_numbering[:-1]
            self.cr()

    def item(self, node, entering):
        if entering:
            node.saved_buf = self.buf
            self.buf = ""
            numbering = self.list_numbering[-1]
            node.prefix = "  " * len(self.list_numbering)
            if numbering is None:
                node.prefix += "\u2022 "
            else:
                node.prefix += "%d. " % numbering
                self.list_numbering[-1] += 1
            self.target_width -= len(node.prefix)
        else:
            self.buf = node.saved_buf + self.item_prefix(self.buf, node.prefix)
            self.target_width += len(node.prefix)

    def item_prefix(self, text, prefix):
        out = []
        for line in text.rstrip("\n").split("\n"):
            out.append(prefix + line)
            # from 2nd line, prefix is all space
            prefix = " " * len(prefix)
        return "\n".join(out) + "\n"
