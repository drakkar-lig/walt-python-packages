from walt.server.images.image import parse_image_fullname
from docker import Client
import requests

COLUMNATE_SPACING = 2

class DockerClient(object):
    def __init__(self):
        self.c = Client(base_url='unix://var/run/docker.sock', version='auto')
    def pull(self, image_fullname):
        fullname, name, user, tag = parse_image_fullname(image_fullname)
        print 'Downloading %s/%s...' % (user, tag)
        for line in self.c.pull(name, tag=requests.utils.quote(tag), stream=True):
            pass
        print 'Done.'

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

def display_transient_label(stdout, label):
    stdout.write(label)
    stdout.flush()

def hide_transient_label(stdout, label):
    # override with space
    display_transient_label(stdout, '\r%s\r' % (' '*len(label)))

