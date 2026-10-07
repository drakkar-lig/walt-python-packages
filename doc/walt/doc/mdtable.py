import re

from walt.doc.color import (
    RE_ESC_COLOR,
    apply_esc_sequence,
    get_transition_esc_sequence,
)

RE_WORD_SPACING = re.compile(r"[ \n]+")
RE_HEADER_SEP_LINE = re.compile("-+:? *[|] *:?-+")
ALIGN_LEFT = -1
ALIGN_CENTER = 0
ALIGN_RIGHT = 1


def detect_table(buf):
    return RE_HEADER_SEP_LINE.search(buf) is not None


def analyse_table(buf):
    lines = buf.splitlines()
    for idx, line in enumerate(lines):
        if RE_HEADER_SEP_LINE.search(line):
            header_idx = idx
            header_sep_line = line
            break
    alignments = []
    for sep in header_sep_line.strip().strip("|").split("|"):
        sep = sep.strip()
        aligndef = (sep.startswith(":"), sep.endswith(":"))
        alignments.append(
            {
                (False, False): ALIGN_LEFT,
                (True, False): ALIGN_LEFT,
                (True, True): ALIGN_CENTER,
                (False, True): ALIGN_RIGHT,
            }[aligndef]
        )
    num_cols = len(alignments)
    table_content = []
    for idx, line in enumerate(lines):
        if idx == header_idx:
            continue
        if line.strip() == "":
            continue
        row = [cell.strip() for cell in line.strip().strip("|").split("|")]
        row = row[:num_cols]
        row += [""] * (num_cols - len(row))
        table_content.append(row)
    return table_content, alignments


def align(text, real_text_len, field_len, alignment):
    if alignment == ALIGN_LEFT:
        return text + " " * (field_len - real_text_len)
    elif alignment == ALIGN_RIGHT:
        return " " * (field_len - real_text_len) + text
    else:  # center
        left_len = (field_len - real_text_len) // 2
        right_len = field_len - real_text_len - left_len
        return " " * left_len + text + " " * right_len


def horizontal_line(col_widths, left_char, sep_char, right_char):
    return (
        left_char
        + sep_char.join("\u2500" * (w + 2) for w in col_widths)
        + right_char
        + "\n"
    )


def get_col_widths(md_renderer, table_content):
    """Return the width of each column. Columns are as wide as their longest
    cell, unless the table does not fit in the available width. In this case
    we shrink the widest columns first (their cells will be wrapped), without
    going below the length of the longest word of the column."""
    real_len = md_renderer.real_text_len
    columns = list(zip(*table_content))
    widths = [max(real_len(cell) for cell in col) for col in columns]
    min_widths = [
        max(real_len(word) for cell in col for word in RE_WORD_SPACING.split(cell))
        for col in columns
    ]
    # borders: 1 char before each column + 1 at the end, and 2 spaces of padding
    # around each column.
    available = md_renderer.target_width - (3 * len(columns) + 1)
    while sum(widths) > available:
        shrinkable = [i for i, w in enumerate(widths) if w > min_widths[i]]
        if len(shrinkable) == 0:
            break  # cannot do better
        widest = max(shrinkable, key=lambda i: widths[i])
        widths[widest] -= 1
    return widths


def wrap_cell(md_renderer, text, width):
    """Return the lines of this cell once wrapped to the given width."""
    if md_renderer.real_text_len(text) <= width:
        return [text]
    lines = md_renderer.wrap_escaped(text, width=width, justify=False).split("\n")
    # A formatting (bold, code, ...) may span several lines of the cell, but we
    # have to draw the table borders (and other cells) between these lines.
    # So make each line self-contained: restore the context of the table at
    # the end of each line, and enter back the cell context at the start of
    # next one.
    base_state = md_renderer.contexts[-1]
    state = base_state
    result = []
    for line in lines:
        prefix = get_transition_esc_sequence(base_state, state)
        for esc_sequence in RE_ESC_COLOR.findall(line):
            state = apply_esc_sequence(state, esc_sequence)
        suffix = get_transition_esc_sequence(state, base_state)
        result.append(prefix + line + suffix)
    return result


def render_row(md_renderer, row, col_widths, alignments, bold=False):
    wrapped_cells = [
        wrap_cell(md_renderer, cell, width) for cell, width in zip(row, col_widths)
    ]
    height = max(len(lines) for lines in wrapped_cells)
    for line_idx in range(height):
        for col_idx, lines in enumerate(wrapped_cells):
            line = lines[line_idx] if line_idx < len(lines) else ""
            md_renderer.lit("\u2502 ")
            if bold:
                md_renderer.stack_context(bold=True)
            md_renderer.lit(
                align(
                    line,
                    md_renderer.real_text_len(line),
                    col_widths[col_idx],
                    alignments[col_idx],
                )
            )
            if bold:
                md_renderer.pop_context()
            md_renderer.lit(" ")
        md_renderer.lit("\u2502\n")


def render_table(md_renderer, buf):
    table_content, alignments = analyse_table(buf)
    col_widths = get_col_widths(md_renderer, table_content)
    # print top line
    md_renderer.lit(horizontal_line(col_widths, "\u250c", "\u252c", "\u2510"))
    # print header
    render_row(
        md_renderer,
        table_content[0],
        col_widths,
        [ALIGN_CENTER] * len(col_widths),
        bold=True,
    )
    # print value rows
    separation_line = horizontal_line(col_widths, "\u251c", "\u253c", "\u2524")
    for row in table_content[1:]:
        md_renderer.lit(separation_line)
        render_row(md_renderer, row, col_widths, alignments)
    # print bottom line
    md_renderer.lit(horizontal_line(col_widths, "\u2514", "\u2534", "\u2518"))
