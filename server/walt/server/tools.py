from collections import namedtuple
from itertools import takewhile, izip
import cPickle as pickle
import re

COLUMNATE_SPACING = 2

PARAGRAPH_FORMATING = """\

\033[1m\
%(title)s
\033[0m\

%(content)s

%(footnote)s"""

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

def columnate_iterate_tty(tabular_data, header = None):
    tabular_data = columnate_sanitize_data(tabular_data)
    if header is not None:
        header = columnate_sanitize_header(header)
    all_rows = []
    str_format = None
    for row in columnate_iterate_rows(tabular_data, header):
        all_rows.append(row)
        new_str_format, sep_line = get_columnate_format(*all_rows)
        if new_str_format == str_format:
            yield columnate_format_row(str_format, sep_line, row)
        else:
            # new row has larger columns, re-print
            if str_format is not None:
                yield '\x1b[%(up)dA' % dict(up=len(all_rows)-1)
            str_format = new_str_format
            yield ''.join(columnate_format_row(str_format, sep_line, row) \
                             for row in all_rows)

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

# are you sure you want to understand what follows? This is sorcery...
nt_index = 0
nt_classes = {}
def to_named_tuple(d):
    global nt_index
    code = pickle.dumps(sorted(d.keys()))
    if code not in nt_classes:
        base = namedtuple('NamedTuple_%d' % nt_index, d.keys())
        class NT(base):
            def update(self, **kwargs):
                d = self._asdict()
                d.update(**kwargs)
                return to_named_tuple(d)
        nt_classes[code] = NT
        nt_index += 1
    return nt_classes[code](**d)

def merge_named_tuples(nt1, nt2):
    d = nt1._asdict()
    d.update(nt2._asdict())
    return to_named_tuple(d)

def update_template(path, template_env):
        with open(path, 'r+') as f:
            template_content = f.read()
            file_content = template_content % template_env
            f.seek(0)
            f.write(file_content)
            f.truncate()

def try_encode(s, encoding):
    if encoding is None:
        return False
    try:
        s.encode(encoding)
        return True
    except UnicodeError:
        return False

def format_node_models_list(node_models):
    if len(node_models) == 1:
        return node_models[0]
    prefix_len = len(tuple(takewhile(lambda s: len(set(s)) == 1, izip(*node_models))))
    prefix = node_models[0][:prefix_len]
    regex_result = prefix + '[' + '|'.join(m[prefix_len:] for m in node_models) + ']'
    simple_result = ','.join(node_models)
    if len(regex_result) < len(simple_result):
        return regex_result
    else:
        return simple_result
