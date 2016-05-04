#!/usr/bin/env python
import sys, imp
from dev.api.fake import FakeObject, FakePackage 

DEBUG=False

class SourceImporter(object):
    ''' When activate() is called, this object re-defines the import mechanism:
        * Source code in user-specified source packages is imported as usual
        * Any other module import returns a fake module.

        This allows to load modules of the source code and use introspection,
        even if this code is not installed on the development machine.

        For instance, it does not make sense to install walt-node and its
        dependencies on the development machine. With this mechanism we can avoid
        this installation and still load and use introspection on this code.
    '''
    def __init__(self, src_packages):
        self.import_path = []
        # walt is a namespace package, because of this it may be already imported
        # if a walt package is installed.
        # let's discard it.
        if 'walt' in sys.modules:
            del sys.modules['walt']
        # define fake packages linking to the source directories
        for mod, path in src_packages.items():
            sys.modules[mod] = FakePackage([path])

    def activate(self):
        # register us as a module finder
        sys.meta_path = [self]

    def register_module(self, modname, mod):
        sys.modules[modname] = mod
        return mod

    def pathname_to_module_path(self, pathname):
        '''converts ./server/walt/server/daemon.py
           to walt.server.daemon'''
        fullname = pathname.strip('./').replace('/','.')
        if fullname.endswith('.py'):
            fullname = fullname[:-3]
        fullname = '.'.join(fullname.split('.')[1:])
        return fullname

    def find_module(self, fullname, path=None):
        '''called when a module is searched for'''
        # return us as a module loader
        return self
 
    def load_module(self, fullname):
        '''called when a module must be loaded'''
        # if already loaded, return it
        if fullname in sys.modules:
            return sys.modules[fullname]
        # if this is a module of a package...
        if '.' in fullname:
            package, name = fullname.rsplit('.', 1)
            # ... load the package first
            if package not in sys.modules:
                self.load_module(package)
            # ... if the package is a FakeObject, the
            # module itself is also a FakeObject
            if isinstance(sys.modules[package], FakeObject):
                return self.register_module(fullname, FakeObject())
            else:
                # otherwise insert the path of the package in the
                # search path
                dirs = sys.modules[package].__path__[:]
        else:
            # otherwise we do not know where to look for
            name = fullname
            dirs = []
        # if we are loading walt.common.daemon and this module
        # internally imports 'evloop', then the module might
        # actually be walt.common.evloop. So let's add
        # walt.common in the search path.
        if len(self.import_path) > 0:
            curr_module_path = self.import_path[-1]
            curr_package_path = curr_module_path.rsplit('/', 1)[0]
            dirs.append(curr_package_path)
        # try to find and import the module
        try:
            module_info = imp.find_module(name, dirs)
            f, pathname, description = module_info
            # using the module file path we can deduce the absolute
            # module path (e.g. walt.common.evloop is the case
            # described above)
            fullname = self.pathname_to_module_path(pathname)
            # imp.load_module() may cause this function to be
            # recursively called (if the module internally performs
            # imports). Let's make sure self.import_path is up-to-date
            # if this happens.
            self.import_path.append(pathname)
            module = imp.load_module(name, *module_info)
            self.import_path = self.import_path[:-1]
            if DEBUG:
                print 'OK -------', fullname
        except ImportError:
            # we could not find the module in the source dirs.
            # return a fake module.
            module = FakeObject()
            if DEBUG:
                print 'FakeObject', fullname
        return self.register_module(fullname, module)

