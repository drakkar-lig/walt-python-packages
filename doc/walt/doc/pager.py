#!/usr/bin/env python
import os
import re
import sys
import traceback

import commonmark
from walt.doc.color import RE_ESC_COLOR
from walt.doc.markdown import MarkdownRenderer
from walt.common.term import TTYSettings, alternate_screen_buffer

SCROLL_HELP = "<up>/<down>, <page-up>/<page-down>: scroll"
TOPICS_HELP = "<tab>/<shift-tab>, <enter>/<backspace>: browse related topics"
Q_HELP = "<q>: quit"

RE_LINKTAGS = re.compile(r"<L+>")


class Pager:
    def __init__(self, authorized_keys):
        self.tty = TTYSettings()
        self.parser = commonmark.Parser()
        self.renderer = MarkdownRenderer()
        self.authorized_keys = authorized_keys

    def start_display(self, **env):
        try:
            self.tty.set_raw_no_echo()
            with alternate_screen_buffer(mouse_wheel_as_arrow_keys=True):
                self.pager_main_loop(**env)
        except Exception as e:
            sys.stdout.write("\r\n\x1b[0m")
            traceback.print_exception(e)
        finally:
            self.tty.restore()

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
        return line + " " * (self.tty.cols - len(line))

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
        footer_lines = ["\u2501" * self.tty.cols + "\r"]
        footer_lines_number = 2  # first estimation
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
            footer_lines = footer_lines[:1]
            while len(help_keys) > 0:
                footer_line_keys, help_keys = (help_keys[0],), help_keys[1:]
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
        return footer_lines_number, footer

    def pager_main_loop(self, **env):
        # activate the pager
        should_load_topic, should_render_markdown, should_redraw = True, True, True
        while True:
            if should_load_topic:
                selected_link_num = 0
                content, index = self.get_md_content(rows=self.tty.rows, **env)
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
                footer_height, footer = self.format_footer(
                    num_lines=num_lines,
                    topic_links=topic_links,
                    **env
                )
                page_height = self.tty.rows - (footer_height + header_height)
                should_render_markdown = False
            if should_redraw:
                # ensure the text after the index is long enough to fill the
                # pager screen
                if len(lines) < index + page_height:
                    lines += [" " * self.tty.cols] * (index + page_height - len(lines))
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
                hidden_lines = lines[:index]
                sys.stdout.write("\r".join(hidden_lines) + "\r")
                displayed = lines[index : index + page_height]
                sys.stdout.write("\r\n".join(displayed) + "\r\n\x1b[0m")
                sys.stdout.write(footer)
                should_redraw = False
            # get keyboard input
            req = None
            while req not in list(self.authorized_keys):
                req = sys.stdin.read(1)
            # process keyboard input
            next_index = index
            next_selected_link_num = selected_link_num
            if req == "q":
                return False  # should not continue
            elif req == "\x7f":  # backspace (return to prev topic)
                if not self.can_return_to_prev_topic(**env):
                    continue  # ignore the keypress
                return True  # return from self.select_topic() called for "\r" below
            elif req == "A":  # up   (we get '\e[A', but '\e' and '[' are ignored)
                next_index = index - 1
            elif req == "B":  # down
                next_index = index + 1
            elif req == "5":  # up
                next_index = index - page_height
            elif req == "6":  # down
                next_index = index + page_height
            elif req == "\t":  # tab
                if len(topic_links) == 0:
                    continue  # ignore the keypress
                next_selected_link_num = (selected_link_num + 1) % (len(topic_links))
                # ensure the viewport includes the selected link
                selected_link_line = topic_links[next_selected_link_num][1]
                if (
                    index + 2 > selected_link_line
                    or index < selected_link_line - page_height + 2
                ):
                    # reposition the viewport to include the selected link
                    next_index = selected_link_line - page_height + 2
            elif req == "Z":  # shift-tab
                if len(topic_links) == 0:
                    continue
                next_selected_link_num = (selected_link_num - 1) % (len(topic_links))
                # ensure the viewport includes the selected link
                selected_link_line = topic_links[next_selected_link_num][1]
                if (
                    index + 2 > selected_link_line
                    or index < selected_link_line - page_height + 2
                ):
                    # reposition the viewport to include the selected link
                    next_index = selected_link_line - 2
            elif req == "\r":  # <enter>: open selected topic
                selected_topic, selected_link_line = topic_links[selected_link_num]
                if (
                    index > selected_link_line
                    or index < selected_link_line - page_height
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
            elif req == "n":  # <n>: "next"
                self.handle_next(**env)
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
            if next_index != index:
                should_redraw = True
            index = next_index
            selected_link_num = next_selected_link_num


class DocPager(Pager):
    def __init__(self, get_md_content):
        super().__init__("qAB56\tZ\r\x7f")
        self._get_md_content = get_md_content

    def display_topic(self, topic):
        content = self.get_md_content(topic, err_out=True)
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

    def can_return_to_prev_topic(self, depth, **env):
        return depth > 0

    def select_topic(self, selected_topic, depth, **env):
        # recursive call to the pager main loop
        return self.pager_main_loop(topic=selected_topic, depth=depth + 1)
