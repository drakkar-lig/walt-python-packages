#!/usr/bin/env python
import inspect, sys, os
sys.path.append(os.getcwd())
from dev.api.source import SourceImporter
# when debugging, the following modules should be
# imported before the import system is altered.
#import pdb, readline

if len(sys.argv) < 2:
    print 'Usage: %s <api_entrypoint_module>' % sys.argv[0]
    sys.exit()

# disable any output
stdout = sys.stdout
sys.stdout = open(os.devnull, 'w')

# indicate source dirs and which module they correspond to
source_packages = {
    'walt.server': './server/walt/server',
    'walt.client': './client/walt/client',
    'walt.common': './common/walt/common',
    'walt.node':   './node/walt/node'
}

# instanciate our import system and activate it.
importer = SourceImporter(source_packages)
importer.activate()
# thanks to this altered import system,
# the next imports will look for code in the current
# source directory only (not in any installed (or missing!) python package).
from walt.common.api import register_api_explorer

class APIExplorer(object):
    def __init__(self):
        self.api_source = ''

    def explore_func(self, func):
        args_str = inspect.formatargspec(*inspect.getargspec(func))
        func_proto = func.__name__ + args_str
        self.api_source += func_proto + '\n'

    def explore_method(self, cls, func):
        self.api_source += cls.__name__ + '.'
        self.explore_func(func)

    def add_attr(self, cls, attr):
        self.api_source += cls.__name__ + '.' + attr + '\n'

# enable api exploration
api_explorer = APIExplorer()
register_api_explorer(api_explorer)

# server API entry point is in the following module
importer.load_module(sys.argv[1])

# restore output
sys.stdout = stdout

# print API source
print api_explorer.api_source,

