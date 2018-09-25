#!/usr/bin/env python
import sys
from walt.client.doc.color import RE_ESC_COLOR
from walt.client.term import TTYSettings

SCROLL_HELP = '<up>/<down>, <page-up>/<page-down>: scroll'
Q_HELP = '<q>: quit'

class Pager:
    def __init__(self):
        self.tty = TTYSettings()
    def display(self, text):
        lines = text.split('\n')
        # we have to behave the same wether the document ends with an empty line
        # (color escape codes excluded) or not
        last_line_without_color = ''.join(RE_ESC_COLOR.split(lines[-1]))
        if len(last_line_without_color) == 0:
            lines = lines[:-1]  # remove last line
        num_lines = len(lines)
        page_height = self.tty.rows-2
        # if the text is not long enough to fill the pager screen, we had empty lines
        if num_lines < page_height:
            lines += [ '' ] * (page_height-num_lines)
            num_lines = page_height
        # adapt footer help
        if num_lines > page_height:
            help_keys = [ SCROLL_HELP, Q_HELP ]
        else:
            help_keys = [ Q_HELP ]
        footer = u'\u2501' * self.tty.cols + \
                 u'\r\n  ' + u' \u2502 '.join(help_keys) + '\r'
        # activate the pager
        try:
            self.tty.set_raw_no_echo()
            index = 0
            old_index = -1
            while True:
                if old_index != index:
                    # to avoid the terminal scrolls, we restart the drawing at
                    # the top-left corner.  But we should not do this the first
                    # time, else we kill the terminal content that existed
                    # before we were launched.
                    if old_index != -1:
                        sys.stdout.write('\x1b[H')
                    # the lines displayed are actually in range
                    # [index:index+page_height], but if one of the previous
                    # lines entered a 'bold' zone for example, (esc code '\e[1m'
                    # and no '\e[21m' code yet to revert it), we should start
                    # the first line with this context. That's why we paste the
                    # whole document up to index+page_height, including the
                    # lines before the view position.  For optimization, we
                    # print these lines on the same tty line, so one line erases
                    # the previous one.
                    hidden_lines = lines[:index]
                    sys.stdout.write('\r'.join(hidden_lines) + '\r')
                    displayed = lines[index:index+page_height]
                    sys.stdout.write('\r\n'.join(displayed) + '\r\n\x1b[0m')
                    sys.stdout.write(footer)
                old_index = index
                # get keyboard input
                req = sys.stdin.read(1)
                if req == 'q':
                    break
                elif req == 'A': # up   (we get '\e[A', but '\e' and '[' are ignored)
                    index = max(index-1, 0)
                elif req == 'B': # down
                    index = min(index+1, num_lines - page_height)
                elif req == '5': # up
                    index = max(index-page_height, 0)
                elif req == '6': # down
                    index = min(index+page_height, num_lines - page_height)
        finally:
            sys.stdout.write('\r\n\x1b[0m')
            self.tty.restore()
