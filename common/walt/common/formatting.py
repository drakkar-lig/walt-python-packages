import re, os
from dateutil.relativedelta import relativedelta

COLUMNATE_SPACING = 2

PARAGRAPH_FORMATING = """\

\033[1m\
%(title)s
\033[0m\

%(content)s

%(footnote)s"""

MAX_PRINTED_NODES = 10
CONJUGATE_REGEXP = r'\b(\w*)\(([^)]*)\)'

def format_sentence(sentence, items,
            label_none, label_singular, label_plural):
    # conjugate if plural or singular
    if len(items) == 1:
        sentence = re.sub(CONJUGATE_REGEXP, r'\1', sentence)
    else:
        sentence = re.sub(CONJUGATE_REGEXP, r'\2', sentence)
    # designation of items
    sorted_items = sorted(items)
    if len(items) > MAX_PRINTED_NODES:
        s_items = '%s %s, %s, ..., %s' % (label_plural, sorted_items[0], sorted_items[1], sorted_items[-1])
    elif len(items) == 0:
        s_items = label_none
    elif len(items) > 1:
        s_items = '%s %s and %s' % (label_plural, ', '.join(sorted_items[:-1]), sorted_items[-1])
    else:   # 1 item
        s_items = '%s %s' % (label_singular, sorted_items[0])
    # almost done
    return sentence % s_items

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
    return format_sentence(sentence, nodes, 'No nodes', 'Node', 'Nodes')

def as_string(item):
    if item == None:
        return ''
    else:
        return str(item)

def columnate_sanitize_data(tabular_data):
    for i in tabular_data:
        yield [as_string(s) for s in i]

def columnate_sanitize_header(header):
    # replace underscores with spaces
    return [ i.replace('_', ' ') for i in header ]

def get_columnate_format(*rows):
    # filter out separation lines
    rows = tuple(row for row in rows if row is not None)
    # compute the max length of elements in each column
    colwidths = [ max([ len(s) for s in i ]) for i in zip(*rows) ]
    # compute a format that should be applied to each record
    str_format = "".join([ '%-' + str(w + COLUMNATE_SPACING) + 's' \
                            for w in colwidths ]) + '\n'
    # compute sep line
    sep_line = str_format % tuple('-' * w for w in colwidths)
    return str_format, sep_line

def columnate_iterate_rows(tabular_data, header = None):
    # yield data
    first = True
    for row in tabular_data:
        if first:
            # if header, yield it
            if header is not None:
                yield tuple(header)
                yield None  # will be understood as a separation line
            first = False
        yield tuple(row)

def columnate_format_row(str_format, sep_line, row):
    if row is None:
        return sep_line
    else:
        return str_format % row

def columnate(tabular_data, header = None):
    tabular_data = tuple(columnate_sanitize_data(tabular_data))
    if len(tabular_data) == 0:
        return ''
    if header is not None:
        header = columnate_sanitize_header(header)
    str_format, sep_line = get_columnate_format(header, *tabular_data)
    formatted = ''.join(columnate_format_row(str_format, sep_line, row) \
        for row in columnate_iterate_rows(tabular_data, header))
    return formatted[:-1]    # remove ending eol

def columnate_iterate_tty(tabular_data, tty_rows, tty_cols, header):
    tabular_data = columnate_sanitize_data(tabular_data)
    if header is not None:
        header = columnate_sanitize_header(header)
    all_rows = []
    str_format = None
    for row in columnate_iterate_rows(tabular_data, header):
        all_rows.append(row)
        new_str_format, sep_line = get_columnate_format(*all_rows)
        should_reprint = True
        if str_format is None:
            should_reprint = False
        if should_reprint and new_str_format == str_format:
            should_reprint = False
        if should_reprint and tty_rows < len(all_rows) +1:
            should_reprint = False
        if should_reprint:
            all_rows_formatted = list(columnate_format_row(new_str_format, sep_line, row) \
                                         for row in all_rows)
            if max(len(line) for line in all_rows_formatted) > tty_cols:
                should_reprint = False
        str_format = new_str_format
        if should_reprint:
            yield '\x1b[%(up)dA' % dict(up=len(all_rows)-1)
            yield ''.join(all_rows_formatted)
        else:
            yield columnate_format_row(str_format, sep_line, row)

def display_transient_label(stdout, label):
    stdout.write('\r' + label + ' ')
    stdout.flush()

def hide_transient_label(stdout, label):
    # override with space
    stdout.write('\r%s\r' % (' '*len(label)))
    stdout.flush()

def indicate_progress(stdout, label, stream, checker = None):
    full_label = ''
    for idx, line in enumerate(stream):
        hide_transient_label(stdout, full_label)
        if checker:
            checker(line)
        progress = "\\|/-"[idx % 4]
        full_label = '%s... %s' % (label, progress)
        display_transient_label(stdout, full_label)
    hide_transient_label(stdout, full_label)
    stdout.write('%s... done.\n' % label)
    stdout.flush()

def format_paragraph(title, content, footnote=None):
    if footnote:
        footnote += '\n\n'
    else:
        footnote = ''
    return PARAGRAPH_FORMATING % dict(
                                    title = title,
                                    content = content,
                                    footnote = footnote)

attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']
def human_readable_delay(seconds):
    if seconds < 1:
        seconds = 1
    delta = relativedelta(seconds=seconds)
    items = []
    for attr in attrs:
        attr_val = getattr(delta, attr)
        if attr_val == 0:
            continue
        plur_or_sing_attr = attr if attr_val > 1 else attr[:-1]
        items.append('%d %s' % (attr_val, plur_or_sing_attr))
    # keep only 2 items max, this is enough granularity for a human.
    items = items[:2]
    return ' and '.join(items)

BOX_CHARS = {
    True: { 'top-left': u'\u250c', 'horizontal': u'\u2500', 'top-right': u'\u2510',
            'vertical': u'\u2502', 'bottom-left': u'\u2514', 'bottom-right': u'\u2518' },
    False: { 'top-left': ' ', 'horizontal': '-', 'top-right': ' ',
            'vertical': '|', 'bottom-left': ' ', 'bottom-right': ' ' }
}

def char_len(line):
    unescaped = re.sub('\x1b' + r'[^m]*m', '', line)
    return len(unescaped)

def framed(title, section):
    box_c = BOX_CHARS[os.isatty(1)]
    lines = [ '' ] + section.splitlines()
    lengths = [ char_len(line) for line in lines ]
    max_width = max(lengths + [ len(title) ])
    top_line = box_c['top-left'] + ' ' + title + ' ' + \
               box_c['horizontal'] * (max_width - len(title)) + box_c['top-right']
    middle_lines = [ (box_c['vertical'] + ' ' + line + \
                      ' ' * (max_width - lengths[i] + 1) + \
                      box_c['vertical']) for i, line in enumerate(lines) ]
    bottom_line = box_c['bottom-left'] + box_c['horizontal'] * (max_width + 2) + \
                  box_c['bottom-right']
    return top_line + '\n' + '\n'.join(middle_lines) + '\n' + bottom_line

def highlight(text):
    if not os.isatty(1):
        return text
    lines = text.strip().splitlines()
    # use DIM and BOLD escape codes
    line_format = "\x1b[1;2m%s\x1b[0m"
    return '\n'.join((line_format % line) for line in lines)
