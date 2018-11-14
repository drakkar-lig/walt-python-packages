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

def header_underline(colwidths):
    return [ '-' * w for w in colwidths ]

def columnate_sanitize(tabular_data, header = None):
    # stringify all (and work on a copy)
    tabular_data_copy = [ [as_string(s) for s in i] for i in tabular_data ]
    # if header is specified, replace underscores with spaces
    if header != None:
        header = [ i.replace('_', ' ') for i in header ]
    return tabular_data_copy, header

def get_columnate_format(tabular_data, header = None):
    # compute the max length of elements in each column
    colwidths = [ max([ len(s) for s in i ]) for i in zip(header, *tabular_data) ]
    # compute a format that should be applied to each record
    str_format = "".join([ '%-' + str(w + COLUMNATE_SPACING) + 's' \
                            for w in colwidths ])
    return str_format, colwidths

def columnate_iterate(tabular_data, str_format, colwidths, header = None):
    # yield data
    first = True
    for record in tabular_data:
        if first:
            # if header, yield it
            if header is not None:
                yield str_format % tuple(header)
                yield str_format % tuple(header_underline(colwidths))
            first = False
        yield str_format % tuple(record)

def columnate(tabular_data, header = None):
    tabular_data, header = columnate_sanitize(tabular_data, header)
    str_format, colwidths = get_columnate_format(tabular_data, header)
    it = columnate_iterate(tabular_data, str_format, colwidths, header)
    return '\n'.join(it)

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
