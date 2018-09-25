#!/usr/bin/env python
import CommonMark, textwrap
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import Terminal256Formatter
from collections import namedtuple
from walt.client.doc.color import *
from walt.client.term import TTYSettings

MAX_TARGET_WIDTH = 120
FORMAT_ATTRS = ['bg_color', 'fg_color', 'underline', 'bold', 'dim']

FG_COLOR_MARKDOWN = FG_COLOR_BLACK
BG_COLOR_MARKDOWN = BG_COLOR_WHITE
FG_COLOR_SOURCE_CODE = FG_COLOR_DARK_YELLOW
BG_COLOR_SOURCE_CODE = BG_COLOR_LIGHT_GREY
FG_COLOR_URL = FG_COLOR_BLUE
FG_COLOR_HEADING = FG_COLOR_DARK_RED

class FormatState(namedtuple('FormatState', FORMAT_ATTRS)):
    def alter(self, **kwargs):
        state = dict(**self._asdict())
        state.update(**kwargs)
        return FormatState(**state)

class MarkdownRenderer:
    def __init__(self, *args, **kwargs):
        self.list_numbering = []
        # initialize context with current terminal setup (default for all attrs)
        init_state = FormatState(bg_color=BG_COLOR_DEFAULT, fg_color=FG_COLOR_DEFAULT,
                            underline=UNDERLINE_OFF, bold=BOLD_OFF, dim=DIM_OFF)
        self.contexts = [ init_state ]
        tty = TTYSettings()
        self.target_width = min(tty.cols, MAX_TARGET_WIDTH)
    def render(self, text):
        parser = CommonMark.Parser()
        ast = parser.parse(text)
        walker = ast.walker()
        self.buf = ''
        event = walker.nxt()
        while event is not None:
            type_ = event['node'].t
            if not hasattr(self, type_):
                raise NotImplementedError(type_)
            getattr(self, type_)(event['node'], event['entering'])
            event = walker.nxt()
        return self.buf
    def document(self, node, entering):
        if entering:
            self.stack_context( fg_color = FG_COLOR_MARKDOWN,
                                bg_color = BG_COLOR_MARKDOWN)
        else:
            # markdown background color should span to right edge
            self.buf = self.buf.replace('\n', '\033[K\n')
            self.pop_context()
    def lit(self, s):
        self.buf += s
    def text(self, node, entering=None):
        self.lit(node.literal)
    def get_esc_sequence(self, old, new):
        codes = []
        for name in FORMAT_ATTRS:
            if getattr(new, name) != getattr(old, name):
                codes.append(str(getattr(new, name)))
        if len(codes) == 0:
            return ''
        else:
            return '\x1b[' + ';'.join(codes) + 'm'
    def stack_context(self, **kwargs):
        curr_state = self.contexts[-1]
        new_state = curr_state.alter(**kwargs)
        self.lit(self.get_esc_sequence(curr_state, new_state))
        self.contexts.append(new_state)
    def pop_context(self):
        curr_state = self.contexts[-1]
        new_state = self.contexts[-2]
        self.lit(self.get_esc_sequence(curr_state, new_state))
        self.contexts = self.contexts[:-1]
    def cr(self):
        self.lit('\n')
    def softbreak(self, node=None, entering=None):
        self.cr()
    def linebreak(self, node=None, entering=None):
        self.cr()
    def html_inline(self, node, entering):
        self.lit(node.literal)
    def link(self, node, entering):
        if entering:
            pass
        else:
            self.lit(' (')
            self.stack_context(fg_color = FG_COLOR_URL)
            self.lit(node.destination)
            self.pop_context()
            self.lit(')')
    def paragraph(self, node, entering):
        if entering:
            node.saved_buf = self.buf
            self.buf = ''
        else:
            self.buf = node.saved_buf + self.wrap_escaped(self.buf)
            self.cr()
            self.cr()
    def block_quote(self, node, entering):
        if entering:
            node.saved_buf = self.buf
            self.target_width -= 2
            self.buf = ''
        else:
            self.buf = node.saved_buf + self.quoted(self.buf)
            self.target_width += 2
            self.cr()
    def wrap_escaped(self, text):
        # textwrap.fill does not work well because of the escape sequences
        wrapped_lines = []
        curr_line = ''
        curr_len = 0
        for line in text.split('\n'):
            for word in line.split(' '):
                wordlen = len(''.join(RE_ESC_COLOR.split(word)))
                if curr_len + 1 + wordlen > self.target_width:
                    wrapped_lines.append(curr_line)
                    curr_line = ' ' + word
                    curr_len = 1 + wordlen
                else:
                    curr_line += ' ' + word
                    curr_len += 1 + wordlen
            wrapped_lines.append(curr_line)
            curr_line = ''
            curr_len = 0
        return '\n'.join(wrapped_lines)
    def quoted(self, text):
        return '\n'.join((u' \u2588' + line) for line in text.rstrip('\n').split('\n')) + '\n'
    def heading(self, node, entering):
        if entering:
            level = 1 if node.level is None else node.level
            self.cr()
            self.stack_context(fg_color = FG_COLOR_HEADING, bold = BOLD_ON)
            self.lit('#'*level + ' ')
            self.underline(None, True)
        else:
            self.underline(None, False)
            self.pop_context()
            self.cr()
            self.cr()
    def underline(self, node, entering):
        if entering:
            self.stack_context(underline = UNDERLINE_ON)
        else:
            self.pop_context()
    def strong(self, node, entering):
        if entering:
            self.stack_context(bold = BOLD_ON)
        else:
            self.pop_context()
    def emph(self, node, entering):
        if entering:
            self.stack_context(dim = DIM_ON)
        else:
            self.pop_context()
    def code(self, node, entering):
        self.stack_context( fg_color = FG_COLOR_SOURCE_CODE,
                            bg_color = BG_COLOR_SOURCE_CODE)
        # replace space with non-breaking space.
        self.lit(node.literal.replace(' ', u'\xa0'))
        self.pop_context()
    def pre_format_code_block(self, text):
        text = textwrap.dedent(text)
        text = '\n'.join(line.rstrip() for line in text.rstrip('\n').split('\n'))
        return text
    # Since pygments output includes escape codes to reset the foreground
    # or background color, we have to make a pass to revert those escape
    # codes and get the default colors we want.
    def fix_pygments_default_colors(self, s, default_fg, default_bg):
        reset_all = "0;%s;%s" % (str(default_fg), str(default_bg))
        mapping = {
                    39: str(default_fg), # default fg color
                    49: str(default_bg), # default bg color
                     0: reset_all
        }
        s2 = ''
        start = 0
        end = 0
        for m in RE_ESC_COLOR.finditer(s):
            start = m.start()
            s2 += s[end:start] + '\x1b['
            codes = (int(c) for c in m.group()[2:-1].split(';'))
            s2 += ';'.join(mapping.get(code, str(code)) for code in codes) + 'm'
            end = m.end()
        s2 += s[end:]
        return s2
    def code_block(self, node, entering):
        code_text = self.pre_format_code_block(node.literal)
        code_width = max(len(line) for line in code_text.split('\n')) + 1
        code_width = max(code_width, self.target_width)
        try:
            lexer = get_lexer_by_name(node.info)
            colored_text = highlight(code_text, lexer, Terminal256Formatter())
            colored_text = self.fix_pygments_default_colors(colored_text,
                                   FG_COLOR_SOURCE_CODE, BG_COLOR_SOURCE_CODE)
        except:
            colored_text = code_text
        for code_line, colored_line in zip(
                    code_text.split('\n'), colored_text.split('\n')):
            self.stack_context( fg_color = FG_COLOR_SOURCE_CODE,
                                bg_color = BG_COLOR_SOURCE_CODE)
            # paste the colored line, then kill ('\e[K') in order to paint the rest
            # with background color of source code, then move to the right ('\e[<N>C')
            # up to the edge of code block
            self.lit(colored_line + '\x1b[K\x1b[%dC' % (code_width-len(code_line)))
            # this will restore markdown background color
            self.pop_context()
            # line feed
            self.cr()
        self.cr()
    def list(self, node, entering):
        if entering:
            if node.list_data['type'] == 'bullet':
                self.list_numbering.append(None)
            else:
                self.list_numbering.append(1)
        else:
            self.list_numbering = self.list_numbering[:-1]
            self.cr()
    def item(self, node, entering):
        if entering:
            node.saved_buf = self.buf
            self.buf = ''
            numbering = self.list_numbering[-1]
            node.prefix = '  ' * len(self.list_numbering)
            if numbering is None:
                node.prefix += u'\u2022 '
            else:
                node.prefix += '%d. ' % numbering
                self.list_numbering[-1] += 1
            self.target_width -= len(node.prefix)
        else:
            self.buf = node.saved_buf + self.item_prefix(self.buf, node.prefix)
            self.target_width += len(node.prefix)
    def item_prefix(self, text, prefix):
        out = []
        for line in text.rstrip('\n').split('\n'):
            out.append(prefix + line)
            # from 2nd line, prefix is all space
            prefix = ' ' * len(prefix)
        return '\n'.join(out) + '\n'
