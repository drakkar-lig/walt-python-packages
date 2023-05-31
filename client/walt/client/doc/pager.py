#!/usr/bin/env python
import os
import re
import sys
import traceback

import commonmark
from walt.client.doc.color import RE_ESC_COLOR
from walt.client.doc.markdown import MarkdownRenderer
from walt.common.term import TTYSettings, alternate_screen_buffer

SCROLL_HELP = "<up>/<down>, <page-up>/<page-down>: scroll"
TOPICS_HELP = "<tab>/<shift-tab>, <enter>/<backspace>: browse related topics"
Q_HELP = "<q>: quit"

RE_LINKTAGS = re.compile(r"<L+>")


class Pager:
    def __init__(self, get_md_content):
        self.tty = TTYSettings()
        self.get_md_content = get_md_content
        self.parser = commonmark.Parser()
        self.renderer = MarkdownRenderer()
        self.debug_s = ""

    def display_topic(self, topic):
        content = self.get_md_content(topic, err_out=True)
        if content is None:
            return
        if os.isatty(sys.stdout.fileno()):
            try:
                self.tty.set_raw_no_echo()
                with alternate_screen_buffer(mouse_wheel_as_arrow_keys=True):
                    self.pager_main_loop(topic, 0)
            except Exception as e:
                sys.stdout.write("\r\n\x1b[0m")
                traceback.print_exception(e)
            finally:
                self.tty.restore()
        else:
            print(content)
            # For debugging colors with hexdump, prefer:
            # print(MarkdownRenderer().render(content))

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

    def adapt_footer_height(self, num_lines, topic_links, depth):
        footer = "\u2501" * self.tty.cols + "\r\n"
        # check if we can feet all in one help line
        page_height = self.tty.rows - 2
        help_keys = []
        if num_lines > page_height:
            help_keys += [SCROLL_HELP]
        if len(topic_links) > 0 or depth > 0:
            help_keys += [TOPICS_HELP]
        help_keys += [Q_HELP]
        lower_line = " " + " \u2502 ".join(help_keys)
        if len(lower_line) <= self.tty.cols:
            # ok for one line
            footer += lower_line + "\r"
        else:
            # use two help lines
            footer += " " + " \u2502 ".join((SCROLL_HELP, Q_HELP)) + "\r\n"
            footer += " " + TOPICS_HELP + "\r"
            page_height -= 1  # 1 less line for file view zone
        return page_height, footer

    def pager_main_loop(self, topic, depth):
        # activate the pager
        should_load_topic = True
        should_render = True
        while True:
            if should_load_topic:
                self.debug_s += "l"
                index = 0
                selected_link_num = 0
                content = self.get_md_content(topic)
                ast = self.parser.parse(content)
                topic_links = self.parse_topic_links(ast)
                should_load_topic = False
            if should_render:
                self.debug_s += "r"
                text = self.renderer.render(ast, selected_link_num)
                lines = text.split("\n")
                # we have to behave the same wether the document ends with an empty line
                # (color escape codes excluded) or not
                last_line_without_color = "".join(RE_ESC_COLOR.split(lines[-1]))
                if len(last_line_without_color) == 0:
                    lines = lines[:-1]  # remove last line
                num_lines = len(lines)
                # adapt footer help
                page_height, footer = self.adapt_footer_height(
                    num_lines, topic_links, depth
                )
                # if the text is not long enough to fill the pager screen, we
                # add blank lines
                if num_lines < page_height:
                    lines += [" " * self.tty.cols] * (page_height - num_lines)
                    num_lines = page_height
                # to avoid the terminal scrolls, we restart the drawing at
                # the top-left corner.
                sys.stdout.write("\x1b[H")
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
                should_render = False
            # get keyboard input
            req = None
            while req not in list("qAB56\tZ\r\x7f"):
                req = sys.stdin.read(1)
                self.debug_s += repr(req)[1:-1]
            # process keyboard input
            next_index = index
            next_selected_link_num = selected_link_num
            if req == "q":
                return False  # should not continue
            elif req == "\x7f":  # backspace (return to prev topic)
                if depth == 0:  # no prev topic to return to
                    continue
                return True  # should continue (and not quit)
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
                    continue
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
                    continue
                # recursive call
                should_continue = self.pager_main_loop(selected_topic, depth + 1)
                if should_continue:
                    # when returning from this selected topic page, we have to
                    # render again
                    should_render = True
                    continue
                else:
                    # we should quit
                    return False
            # limit index value to fit the viewport
            next_index = max(next_index, 0)
            next_index = min(next_index, num_lines - page_height)
            if next_index != index or next_selected_link_num != selected_link_num:
                should_render = True
            index = next_index
            selected_link_num = next_selected_link_num
