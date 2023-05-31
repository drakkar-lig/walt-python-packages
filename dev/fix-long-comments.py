#!/usr/bin/env python3

import sys
import textwrap
from pathlib import Path


def better_wrap(comment, initial_indent, subsequent_indent):
    # try to avoid having just one word moved to last line...
    width = 88
    for i in range(3):
        lines = textwrap.wrap(
            comment,
            width=width,
            initial_indent=initial_indent,
            subsequent_indent=subsequent_indent,
            break_on_hyphens=False,
        )
        if len(lines) > 1 and len(lines[-1].lstrip()) < 15:
            width -= 4
    return lines


def process_comment(fixed_lines, code, comment):
    initial_prefix = code + "# "
    subsequent_prefix = (" " * len(code)) + "# "
    lines = better_wrap(comment, initial_prefix, subsequent_prefix)
    base_len = len(f"{code} # {comment}")
    if len("\n".join(lines)) > 1.5 * base_len:
        # moving the comment before the code
        # should give a better result
        indent = len(code) - len(code.lstrip())
        prefix = (" " * indent) + "# "
        lines = better_wrap(comment, prefix, prefix)
        lines += [code.rstrip()]
    fixed_lines += lines


def detect_start_of_comment(line_comment):
    line_comment = line_comment.lstrip()
    if line_comment[0].isupper():
        return True
    line_comment = line_comment.lower()
    return line_comment.startswith("note:") or line_comment.startswith("tip:")


def process_file(filepath):
    lines = filepath.read_text().splitlines()
    fixed_lines = []
    code, comment = "", ""
    mode = "SEARCH"
    modified = False
    for line in lines:
        start_new_comment = False
        end_prev_comment = False
        add_line_unmodified = False
        if mode == "SEARCH":
            if "#" in line and len(line) > 88:
                line_code, line_comment = line.split("#", maxsplit=1)
                start_new_comment = True
                mode = "FIX"
                modified = True
            else:
                add_line_unmodified = True
        elif mode == "FIX":
            if "#" in line:
                # check if this is a continuation of the current comment
                # (with the same indent) or a new one
                line_code, line_comment = line.split("#", maxsplit=1)
                if (
                    line_code.strip() == ""
                    and len(line_code) == len(code)
                    and not detect_start_of_comment(line_comment)
                ):
                    comment += " " + line_comment.strip()
                else:
                    end_prev_comment = True
                    start_new_comment = True
            else:
                end_prev_comment = True
                add_line_unmodified = True
                mode = "SEARCH"
        # do actions
        if end_prev_comment:
            process_comment(fixed_lines, code, comment)
        if start_new_comment:
            code = line_code
            comment = line_comment.strip()
        if add_line_unmodified:
            fixed_lines.append(line)
    if mode == "FIX":  # file is ending with a comment...
        process_comment(fixed_lines, code, comment)
    if modified:
        # rewrite file
        filepath.write_text("\n".join(fixed_lines) + "\n")
        print(f"{filepath} was fixed.")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        filepath = Path(sys.argv[1])
        process_file(filepath)
    else:
        for filepath in Path(".").glob("*/walt/**/*.py"):
            process_file(filepath)
