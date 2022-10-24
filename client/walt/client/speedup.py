# This file implements a few tricks enabling the walt command
# to load faster.

import os, builtins, sys, locale
from pathlib import Path

# -- 1st workaround --
# Workaround plumbum i18n module loading pkg_resources, which is slow,
# unless locale starts with 'en'. We cannot blindly call setlocale()
# because we do not know which locales are available on the OS where
# walt client is installed.
def fix_plumbum_locale():
    locale.getlocale = lambda *args: ('en_US', 'UTF-8')

# -- 2nd workaround --
# When the walt client is installed on a slow filesystem (such as a
# virtualenv on an NFS-mounted home directory), it can be significantly
# less reactive. If environment variables PY_SLOW_DISK_PREFIX and
# PY_CACHE_PREFIX are defined, we save a copy of python module files
# on faster storage before the command line tool exits, and we modify
# sys.path to target this location.

def get_cache_prefix_info():
    py_slow_disk_prefix = os.environ.get('PY_SLOW_DISK_PREFIX', None)
    py_cache_prefix = os.environ.get('PY_CACHE_PREFIX', None)
    if py_slow_disk_prefix is None or py_cache_prefix is None:
        return None, None
    return py_slow_disk_prefix.rstrip('/'), py_cache_prefix.rstrip('/')

def copy_file(src, dst):
    #print(f'copy_file {src} -> {dst}')
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(Path(src).read_bytes())

def copy_package_files(src_dir, dst_dir):
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    #print('copy_package_files', src_dir)
    for src_entry in src_dir.iterdir():
        if src_entry.is_file() and not src_entry.name.endswith('.py'):
            copy_file(src_entry, dst_dir / src_entry.name)

def cache_modules():
    py_slow_disk_prefix, py_cache_prefix = get_cache_prefix_info()
    py_cache_prefix = Path(py_cache_prefix)
    for modname, mod in sys.modules.items():
        if modname == 'plumbum.colors':
            # the value of sys.modules['plumbum.colors'] is overriden in the code
            # of plumbum/colors.py -- recompute the path
            mod_path = sys.modules['plumbum'].__file__[:-len('__init__.py')] + 'colors.py'
        else:
            mod_path = getattr(mod, '__file__', None)
        if mod_path is not None and mod_path.startswith(py_slow_disk_prefix):
            is_package = getattr(mod, '__path__', None) is not None
            if not mod_path.endswith('/__init__.py'):
                is_package = False
            cache_mod_path = py_cache_prefix / mod_path[1:]  # remove leading slash
            if is_package:
                package_path = mod_path[:-len('/__init__.py')]
                cache_package_path = cache_mod_path.parent
            if not cache_mod_path.exists():
                #print(f'cache {modname}')
                copy_file(mod_path, cache_mod_path)
                if is_package:
                    copy_package_files(package_path, cache_package_path)
            else:
                #print(f'redirect {modname}')
                mod.__file__ = str(cache_mod_path)
                if is_package:
                    mod.__path__ = [ str(cache_package_path) ] + mod.__path__
                if mod.__spec__ is not None:
                    if is_package:
                        mod.__spec__.submodule_search_locations = mod.__path__

def cache_modules_on_faster_disk():
    py_slow_disk_prefix, py_cache_prefix = get_cache_prefix_info()
    if py_slow_disk_prefix is not None:
        new_path = []
        for path in sys.path:
            if path.startswith(py_slow_disk_prefix):
                new_path.append(f'{py_cache_prefix}{path}')
            new_path.append(path)
        if len(new_path) > len(sys.path):   # if different
            # Some modules were already loaded at this point, before we update
            # sys.path variable below. These modules, such as 'walt', 'walt.client'
            # 'walt.client.plugins', etc., were loaded from the initial directory
            # on slow storage. When loading submodules of these first modules,
            # the import system will continue loading from the same directory
            # unless we update their __path__ and __spec__ information.
            # This first call to cache_modules() will do it.
            cache_modules()
            # activate the cache
            sys.path = new_path
            # update the cache before the tool exits
            import atexit; atexit.register(cache_modules)

# -- 3rd workaround --
# The following prevents plumbum to load modules we will not need.
DIVERTLIST = [ 'plumbum.machines', 'plumbum.path', 'plumbum.commands', 'plumbum.cmd' ]
DEBUG = False

real_import = None

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
                package = real_import(name, globals, locals, (item,), level)
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

def divert_unused_plumbum_modules():
    global real_import
    saved_import = __import__
    builtins.__import__ = __myimport__
    if DEBUG:
        indent = 0
        from time import time
        def debug_import(*import_args):
            indent += 2
            t0 = time()
            res = saved_import(*import_args)
            t1 = time()
            indent -= 2
            if t1-t0 > 0.01:
                print('  '*indent, (import_args[0],) + import_args[3:], f'{t1-t0:.3f}')
            return res
        real_import = debug_import
    else:
        real_import = saved_import

# -- Run exerything --
# --------------------
def run():
    fix_plumbum_locale()
    cache_modules_on_faster_disk()
    divert_unused_plumbum_modules()

run()
