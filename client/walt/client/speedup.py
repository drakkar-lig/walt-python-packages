# This file implements a few tricks enabling the walt command
# to load faster.

import builtins, sys, locale

# -- 1st workaround --
# workaround plumbum i18n module loading pkg_resources, which is slow,
# unless locale starts with 'en'. we cannot blindly call setlocale()
# because we do not know which locales are available on the OS where
# walt client is installed.
locale.getlocale = lambda *args: ('en_US', 'UTF-8')

# -- 2nd workaround --
# The following prevents plumbum to load modules we will not need.
DIVERTLIST = [ 'plumbum.machines', 'plumbum.path', 'plumbum.commands', 'plumbum.cmd' ]

DEBUG = False

saved_import = __import__

if DEBUG:
    indent = 0
    from time import time
    def real_import(*import_args):
        global indent
        indent += 2
        t0 = time()
        res = saved_import(*import_args)
        t1 = time()
        indent -= 2
        if t1-t0 > 0.01:
            print('  '*indent, (import_args[0],) + import_args[3:], f'{t1-t0:.3f}')
        return res
else:
    real_import = saved_import

class Dummy:
    pass

def __get_dummy_module__(name):
    if name in sys.modules:
        return True, sys.modules[name]
    else:
        return False, Dummy()

def diverted(name):
    for prefix in DIVERTLIST:
        if name.startswith(prefix):
            return True
    return False

def __myimport__(name, globals=None, locals=None, fromlist=(), level=0):
    import_args = name, globals, locals, fromlist, level
    #print((import_args[0],) + import_args[3:])
    if fromlist is None:
        fromlist = ()
    if level > 0:
        caller_mod_path = tuple(sys._current_frames().values())[0].f_back.f_globals['__name__']
        for item in fromlist:
            item_path = f'{caller_mod_path}.{item}'
            if diverted(item_path):
                package = __myimport__(f'{caller_mod_path}.{item}', globals, locals)
            else:
                package = real_import(name, globals, locals, fromlist=(item,), level=level)
        return package
    if '*' in fromlist or (name in sys.modules and len(fromlist) == 0) or not diverted(name):
        return real_import(*import_args)
    # see https://docs.python.org/3/library/functions.html#import__
    if len(fromlist) > 0:
        found, o = __get_dummy_module__(name)
        for attr_name in fromlist:
            attr_o = Dummy()
            setattr(o, attr_name, attr_o)
        if not found:
            sys.modules[name] = o
        return o
    mod_path = name
    child_mod = __get_dummy_module__(mod_path)
    while True:
        if not '.' in mod_path:
            break
        mod_parent_path, mod_name = mod_path.rsplit('.', maxsplit=1)
        found, parent_mod = __get_dummy_module__(mod_parent_path)
        setattr(parent_mod, mod_name, child_mod)
        if not found:
            sys.modules[mod_parent_path] = parent_mod
        # prepare next loop
        child_mod = parent_mod
        mod_path = mod_parent_path
    return child_mod

builtins.__import__ = __myimport__
