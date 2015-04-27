import os
COLUMNATE_SPACING = 2

# use the following like this:
#
# with AutoCleaner(<cls>) as <var>:
#     ... work_with <var> ...
#
# the <cls> must provide a method cleanup() 
# that will be called automatically when leaving 
# the with construct. 

class AutoCleaner(object):
    def __init__(self, cls):
        self.cls = cls
    def __enter__(self):
        self.instance = self.cls()
        return self.instance
    def __exit__(self, t, value, traceback):
        self.instance.cleanup()
        self.instance = None

def as_string(item):
    if item == None:
        return ''
    else:
        return str(item)

def columnate(tabular_data, header = None):
    # stringify all (and work on a copy)
    tabular_data_copy = [ [as_string(s) for s in i] for i in tabular_data ]
    # if header is specified, add it
    if header != None:
        tabular_data_copy.insert(0, header)
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

def failsafe_makedirs(path):
    # create only if missing
    if not os.path.exists(path):
        os.makedirs(path)

def failsafe_symlink(src, dst):
    # remove existing symlink if any
    if os.path.lexists(dst):
        os.remove(dst)
    # ensure parent dir of dst exists
    failsafe_makedirs(os.path.dirname(dst))
    # create the symlink
    os.symlink(src, dst)

