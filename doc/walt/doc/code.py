"""Terminal rendering of source code blocks (syntax highlighting with pygments,
optional line numbers, breakpoint markers and highlighted line).

This module does not depend on markdown: it is used by the markdown renderer
for code blocks, and directly by tools displaying source code in the pager.
"""
from collections import namedtuple

from walt.doc.color import (
    BG_COLOR_LIGHT_GREY,
    FG_COLOR_BLACK,
    optimize_and_reset_default_colors,
)

FG_COLOR_SOURCE_CODE = FG_COLOR_BLACK
BG_COLOR_SOURCE_CODE = BG_COLOR_LIGHT_GREY
BG_COLOR_SOURCE_CODE_HIGHLIGHT = "103"
BREAKPOINT_MARKER = "⯃"

# plain: the line without escape codes (for computing its width)
# colored: the line with syntax highlighting escape codes; it expects
#          the terminal colors to be set to FG_COLOR_SOURCE_CODE and bg_color
#          when it starts, and does not change them at the end.
CodeLine = namedtuple("CodeLine", ["plain", "colored", "bg_color"])


def _highlight(code_text, language):
    if language is None:
        return code_text
    try:
        from pygments import highlight
        from pygments.formatters import Terminal256Formatter
        from pygments.lexers import get_lexer_by_name
        lexer = get_lexer_by_name(language)
        colored_text = highlight(code_text, lexer, Terminal256Formatter())
        return colored_text.rstrip("\n")
    except Exception:  # syntax highlighting failed: just use the raw code
        return code_text


def _line_prefix(lineno, breakpoints, line_number_width):
    elements = ()
    if breakpoints is not None:
        elements += (BREAKPOINT_MARKER if lineno in breakpoints else " ",)
    if line_number_width is not None:
        elements += (f"{lineno:>{line_number_width}}",)
    if len(elements) > 0:
        elements += ("|",)
        return " ".join(elements) + " "
    return ""


def render_code_lines(code_text, language=None, linenos=False,
                      breakpoints=None, highlight_line=None):
    """Render source code and return a list of CodeLine.

    language: pygments lexer name (e.g., "python3"), or None for no
              syntax highlighting.
    linenos: prefix lines with their line number.
    breakpoints: None (no breakpoint column), or a set of line numbers
              (1-indexed) marked with a breakpoint symbol.
    highlight_line: line number (1-indexed) displayed with a different
              background color, or None.
    """
    code_text = "\n".join(line.rstrip()
                          for line in code_text.rstrip("\n").split("\n"))
    colored_text = _highlight(code_text, language)
    code_lines = code_text.split("\n")
    colored_lines = colored_text.split("\n")
    if linenos:
        line_number_width = len(str(len(code_lines)))
    else:
        line_number_width = None
    prefixes = [_line_prefix(lineno, breakpoints, line_number_width)
                for lineno in range(1, len(code_lines) + 1)]
    code_lines = [p + line for p, line in zip(prefixes, code_lines)]
    colored_lines = [p + line for p, line in zip(prefixes, colored_lines)]
    if highlight_line is not None:
        hl = highlight_line - 1  # 1-indexing -> 0-indexing
        sections = (
            (0, hl, BG_COLOR_SOURCE_CODE),
            (hl, hl + 1, BG_COLOR_SOURCE_CODE_HIGHLIGHT),
            (hl + 1, len(code_lines), BG_COLOR_SOURCE_CODE),
        )
    else:
        sections = ((0, len(code_lines), BG_COLOR_SOURCE_CODE),)
    result = []
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
        for code_line, colored_line in zip(
            section_code_lines, section_colored_text.split("\n")
        ):
            result.append(CodeLine(code_line, colored_line, bg_color))
    return result


def render_code(code_text, **kwargs):
    """Render source code as standalone terminal text (one string, lines
    separated by newlines), with the code background color extending to
    the right edge of the terminal.

    Keyword arguments are the same as render_code_lines().
    """
    lines = []
    for line in render_code_lines(code_text, **kwargs):
        lines.append(f"\x1b[{FG_COLOR_SOURCE_CODE};{line.bg_color}m"
                     f"{line.colored}\x1b[K\x1b[0m")
    return "\n".join(lines)
