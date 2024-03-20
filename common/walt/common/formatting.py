import re

COLUMNATE_SPACING = 2

PARAGRAPH_FORMATING = """\

\033[1m\
%(title)s
\033[0m\

%(content)s

%(footnote)s"""

MAX_PRINTED_NODES = 5
CONJUGATE_REGEXP = r"\b(\w*)\(([^)]*)\)"


def format_sentence(
    sentence, items, label_none, label_singular, label_plural, list_type="and"
):
    # conjugate if plural or singular
    if len(items) == 1:
        sentence = re.sub(CONJUGATE_REGEXP, r"\1", sentence)
    else:
        sentence = re.sub(CONJUGATE_REGEXP, r"\2", sentence)
    # designation of items
    sorted_items = sorted(items)
    if len(items) > MAX_PRINTED_NODES:
        s_items, node_names = ("%d %s" % (len(items), label_plural)), ()
    elif len(items) == 0:
        s_items, node_names = label_none, ()
    elif len(items) > 1:
        s_items, node_names = label_plural + " %s " + list_type + " %s", (
            ", ".join(sorted_items[:-1]),
            sorted_items[-1],
        )
    else:  # 1 item
        s_items, node_names = label_singular + " %s", (sorted_items[0],)
    # almost done
    sentence = (sentence % s_items).capitalize()
    return sentence % node_names


def format_sentence_about_nodes(sentence, nodes):
    """
    example 1:
        input: sentence = '%s seems(seem) dead.', nodes = ['rpi0']
        output: 'Node rpi0 seems dead.'
    example 2:
        input: sentence = '%s seems(seem) dead.', nodes = ['rpi0', 'rpi1', 'rpi2']
        output: 'Nodes rpi0, rpi1 and rpi2 seem dead.'
    (and if there are many nodes, an ellipsis is used.)
    """
    return format_sentence(sentence, nodes, "No nodes", "Node", "Nodes")


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


def display_transient_label(stdout, label):
    stdout.write("\r" + label + " ")
    stdout.flush()


def hide_transient_label(stdout, label):
    # override with space
    stdout.write("\r%s\r" % (" " * len(label)))
    stdout.flush()


def indicate_progress(stdout, label, stream, checker=None):
    full_label = ""
    for idx, line in enumerate(stream):
        hide_transient_label(stdout, full_label)
        if checker:
            checker(line)
        progress = "\\|/-"[idx % 4]
        full_label = "%s... %s" % (label, progress)
        display_transient_label(stdout, full_label)
    hide_transient_label(stdout, full_label)
    stdout.write("%s... done.\n" % label)
    stdout.flush()


def format_paragraph(title, content, footnote=None):
    if footnote:
        footnote += "\n\n"
    else:
        footnote = ""
    return PARAGRAPH_FORMATING % dict(title=title, content=content, footnote=footnote)


attrs = ["years", "months", "days", "hours", "minutes", "seconds"]


def human_readable_delay(seconds):
    from dateutil.relativedelta import relativedelta
    if seconds < 1:
        seconds = 1
    delta = relativedelta(seconds=seconds)
    items = []
    for attr in attrs:
        attr_val = getattr(delta, attr)
        if attr_val == 0:
            continue
        plur_or_sing_attr = attr if attr_val > 1 else attr[:-1]
        items.append("%d %s" % (attr_val, plur_or_sing_attr))
    # keep only 2 items max, this is enough granularity for a human.
    items = items[:2]
    return " and ".join(items)


BOX_CHARS = {
    True: {
        "top-left": "\u250c",
        "horizontal": "\u2500",
        "top-right": "\u2510",
        "vertical": "\u2502",
        "bottom-left": "\u2514",
        "bottom-right": "\u2518",
    },
    False: {
        "top-left": " ",
        "horizontal": "-",
        "top-right": " ",
        "vertical": "|",
        "bottom-left": " ",
        "bottom-right": " ",
    },
}


def framed(title, section):
    import os
    box_c = BOX_CHARS[os.isatty(1)]
    lines = [""] + section.splitlines()
    lengths = [char_len(line) for line in lines]
    max_width = max(lengths + [len(title)])
    top_line = (
        box_c["top-left"]
        + " "
        + title
        + " "
        + box_c["horizontal"] * (max_width - len(title))
        + box_c["top-right"]
    )
    middle_lines = [
        (
            box_c["vertical"]
            + " "
            + line
            + " " * (max_width - lengths[i] + 1)
            + box_c["vertical"]
        )
        for i, line in enumerate(lines)
    ]
    bottom_line = (
        box_c["bottom-left"]
        + box_c["horizontal"] * (max_width + 2)
        + box_c["bottom-right"]
    )
    return top_line + "\n" + "\n".join(middle_lines) + "\n" + bottom_line


def highlight(text):
    import os
    if not os.isatty(1):
        return text
    lines = text.strip().splitlines()
    # use DIM and BOLD escape codes
    line_format = "\x1b[1;2m%s\x1b[0m"
    return "\n".join((line_format % line) for line in lines)
