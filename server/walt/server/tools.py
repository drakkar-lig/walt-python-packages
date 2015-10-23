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

# use the following like this:
#
# with AutoCleaner(<obj>) as <var>:
#     ... work_with <var> ...
#
# <obj> must provide a method cleanup()
# that will be called automatically when leaving 
# the with construct. 

class AutoCleaner(object):
    def __init__(self, obj):
        self.obj = obj
    def __enter__(self):
        return self.obj
    def __exit__(self, t, value, traceback):
        self.obj.cleanup()
        self.obj = None

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

def format_paragraph(title, content, footnote=None):
    if footnote:
        footnote += '\n\n'
    else:
        footnote = ''
    return PARAGRAPH_FORMATING % dict(
                                    title = title,
                                    content = content,
                                    footnote = footnote)


MAX_PRINTED_NODES = 10
CONJUGATE_REGEXP = r'\b(\w*)\((\w*)\)'

def format_sentence_about_nodes(sentence, nodes):
    """
    example 1:
        input: sentence = '% seems(seem) dead.', nodes = ['rpi0']
        output: 'Node rpi0 seems dead.'
    example 2:
        input: sentence = '% seems(seem) dead.', nodes = ['rpi0', 'rpi1', 'rpi2']
        output: 'Nodes rpi0, rpi1 and rpi2 seem dead.'
    (and if there are many nodes, an ellipsis is used.)
    """
    # conjugate if plural or singular
    if len(nodes) > 1:
        sentence = re.sub(CONJUGATE_REGEXP, r'\2', sentence)
    else:
        sentence = re.sub(CONJUGATE_REGEXP, r'\1', sentence)
    # designation of nodes
    sorted_nodes = sorted(nodes)
    if len(nodes) > MAX_PRINTED_NODES:
        s_nodes = 'Nodes %s, %s, ..., %s' % (sorted_nodes[0], sorted_nodes[1], sorted_nodes[-1])
    elif len(nodes) > 1:
        s_nodes = 'Nodes %s and %s' % (', '.join(sorted_nodes[:-1]), sorted_nodes[-1])
    else:
        s_nodes = 'Node %s' % tuple(nodes)
    # almost done
    return sentence % s_nodes

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

