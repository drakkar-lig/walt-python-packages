"""Text formatting helpers for the analysis tool.

This is a subset of walt.common.formatting (WalT project), copied here so
that trackexec does not depend on WalT packages.
"""
import re

COLUMNATE_SPACING = 2

PARAGRAPH_FORMATING = """\

\033[1m\
%(title)s
\033[0m\

%(content)s

%(footnote)s"""


def as_string(item):
    if item is None:
        return ""
    else:
        return str(item)


def columnate_sanitize_data(tabular_data):
    for i in tabular_data:
        yield [as_string(s) for s in i]


def columnate_sanitize_header(header):
    # replace underscores with spaces
    return [i.replace("_", " ") for i in header]


def char_len(line):
    unescaped = re.sub("\x1b" + r"[^m]*m", "", line)
    return len(unescaped)


def pad_right(text, text_length, width):
    return text + (width - text_length) * " "

def pad_left(text, text_length, width):
    return (width - text_length) * " " + text

def columnate_format_row(row, row_lengths, colwidths, padding):
    col_spacing = " " * COLUMNATE_SPACING
    return col_spacing.join(
        pad_func(text, text_length, width)
        for text, text_length, width, pad_func in
            zip(row, row_lengths, colwidths, padding)
    )


def columnate(tabular_data, header=None, shrink_empty_cols=False, align=None):
    tabular_data = tuple(columnate_sanitize_data(tabular_data))
    if len(tabular_data) == 0:
        return ""
    # align cell content on the left if not specified
    if align is None:
        align = "<" * len(tabular_data[0])
    padding = [pad_right if c == "<" else pad_left for c in align]
    if shrink_empty_cols:
        dropped_cols = [
            max(len(cell) for cell in column) == 0 for column in zip(*tabular_data)
        ]
        tabular_data = [
            [cell for i, cell in enumerate(row) if not dropped_cols[i]]
            for row in tabular_data
        ]
        if header is not None:
            header = [t for i, t in enumerate(header) if not dropped_cols[i]]
        padding = [p for i, p in enumerate(padding) if not dropped_cols[i]]
    all_cells = list(tabular_data)
    if header is not None:
        header = columnate_sanitize_header(header)
        all_cells = [header] + all_cells
    all_cell_lengths = [[char_len(cell) for cell in row] for row in all_cells]
    # compute the max length of elements in each column
    colwidths = [max(column) for column in zip(*all_cell_lengths)]
    # add separator line
    if header is not None:
        sep_line_lengths = colwidths
        sep_line_row = ["-" * w for w in colwidths]
        # insert as second line
        all_cell_lengths[1:1] = [sep_line_lengths]
        all_cells[1:1] = [sep_line_row]
    return "\n".join(
        columnate_format_row(row, row_lengths, colwidths, padding)
        for row, row_lengths in zip(all_cells, all_cell_lengths)
    )




def format_paragraph(title, content, footnote=None):
    if footnote:
        footnote += "\n\n"
    else:
        footnote = ""
    return PARAGRAPH_FORMATING % dict(title=title, content=content, footnote=footnote)


attrs = ["years", "months", "days", "hours", "minutes", "seconds"]

