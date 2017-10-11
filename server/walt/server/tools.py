from collections import namedtuple
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

def columnate(tabular_data, header = None):
    # stringify all (and work on a copy)
    tabular_data_copy = [ [as_string(s) for s in i] for i in tabular_data ]
    # if header is specified, add it
    # and replace underscores with spaces
    if header != None:
        tabular_data_copy.insert(0, [ i.replace('_', ' ') for i in header ])
    # compute the max length of elements in each column
    colwidths = [ max([ len(s) for s in i ]) for i in zip(*tabular_data_copy) ]
    # if header, underline it 
    if header != None:
        tabular_data_copy.insert(1, [ '-' * w for w in colwidths ])
    # compute a format that should be applied to each record
    formating = "".join([ '%-' + str(w + COLUMNATE_SPACING) + 's' \
                            for w in colwidths ])
    # format and return
    return '\n'.join(formating % tuple(record) for record in tabular_data_copy)

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
        nt_classes[code] = namedtuple('NamedTuple_%d' % nt_index, d.keys())
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
