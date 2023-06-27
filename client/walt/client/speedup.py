# This file implements a few tricks enabling the walt command
# to run faster.
# One can also define env variable PROFILE_IMPORTS in order
# to get a treemap view of module import delays, e.g.:
# $ PROFILE_IMPORTS=1 walt node show

import atexit
import builtins
import locale
import os
import sys
from pathlib import Path

# -- 1st hack --
# register a faster exit function.
# Note: atexit executes function in the reverse order these functions
# were registered. Thus we must ensure _fastexit is the first handler
# registered with atexit.register(), otherwise shortcuting the exit
# procedure would affect previously registered handlers.
exit_code = None
orig_exit = sys.exit


def _exit_code_recorder(code):
    global exit_code
    exit_code = code
    orig_exit(code)


def _fastexit():
    if not isinstance(exit_code, int):
        return  # continue with normal exit procedure
    # fast exit
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)


def register_faster_exit():
    sys.exit = _exit_code_recorder
    atexit.register(_fastexit)


# -- 2nd hack --
# Workaround plumbum i18n module loading pkg_resources, which is slow,
# unless locale starts with 'en'. We cannot blindly call setlocale()
# because we do not know which locales are available on the OS where
# walt client is installed.
def fix_plumbum_locale():
    locale.getlocale = lambda *args: ("en_US", "UTF-8")


# -- 3rd hack --
# When the walt client is installed on a slow filesystem (such as a
# virtualenv on an NFS-mounted home directory), it can be significantly
# less reactive. If environment variables PY_SLOW_DISK_PREFIX and
# PY_CACHE_PREFIX are defined, we save a copy of python module files
# on faster storage before the command line tool exits, and we modify
# sys.path to target this location.


def get_cache_prefix_info():
    py_slow_disk_prefix = os.environ.get("PY_SLOW_DISK_PREFIX", None)
    py_cache_prefix = os.environ.get("PY_CACHE_PREFIX", None)
    if py_slow_disk_prefix is None or py_cache_prefix is None:
        return None, None
    return py_slow_disk_prefix.rstrip("/"), py_cache_prefix.rstrip("/")


def copy_file(src, dst):
    # print(f'copy_file {src} -> {dst}')
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(Path(src).read_bytes())


def copy_package_files(src_dir, dst_dir):
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    # print('copy_package_files', src_dir)
    for src_entry in src_dir.iterdir():
        if src_entry.is_file() and not src_entry.name.endswith(".py"):
            copy_file(src_entry, dst_dir / src_entry.name)


def cache_modules():
    py_slow_disk_prefix, py_cache_prefix = get_cache_prefix_info()
    py_cache_prefix = Path(py_cache_prefix)
    for modname, mod in sys.modules.items():
        if modname == "plumbum.colors":
            # the value of sys.modules['plumbum.colors'] is overriden in the code
            # of plumbum/colors.py -- recompute the path
            mod_path = (
                sys.modules["plumbum"].__file__[: -len("__init__.py")] + "colors.py"
            )
        else:
            mod_path = getattr(mod, "__file__", None)
        if mod_path is not None and mod_path.startswith(py_slow_disk_prefix):
            is_package = getattr(mod, "__path__", None) is not None
            if not mod_path.endswith("/__init__.py"):
                is_package = False
            cache_mod_path = py_cache_prefix / mod_path[1:]  # remove leading slash
            if is_package:
                package_path = mod_path[: -len("/__init__.py")]
                cache_package_path = cache_mod_path.parent
            if not cache_mod_path.exists():
                # print(f'cache {modname}')
                copy_file(mod_path, cache_mod_path)
                if is_package:
                    copy_package_files(package_path, cache_package_path)
            else:
                # print(f'redirect {modname}')
                mod.__file__ = str(cache_mod_path)
                if is_package:
                    mod.__path__ = [str(cache_package_path)] + mod.__path__
                if mod.__spec__ is not None:
                    if is_package:
                        mod.__spec__.submodule_search_locations = mod.__path__


def cache_modules_on_faster_disk():
    py_slow_disk_prefix, py_cache_prefix = get_cache_prefix_info()
    if py_slow_disk_prefix is not None:
        new_path = []
        for path in sys.path:
            if path.startswith(py_slow_disk_prefix):
                new_path.append(f"{py_cache_prefix}{path}")
            new_path.append(path)
        if len(new_path) > len(sys.path):  # if different
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
            atexit.register(cache_modules)


# -- 4th hack --
# The following prevents plumbum to load modules we will not need.
DIVERTLIST = ["plumbum.machines", "plumbum.path", "plumbum.commands", "plumbum.cmd"]
PROFILE_IMPORTS = ('PROFILE_IMPORTS' in os.environ)
DEBUG_IMPORTS = ('DEBUG_IMPORTS' in os.environ)
DEBUG_NAMES = []

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
    global DEBUG_NAMES
    # print((import_args[0],) + import_args[3:])
    if fromlist is None:
        fromlist = ()
    if name in sys.modules and len(fromlist) == 0:
        # fast path
        top_level_name = name.split('.', maxsplit=1)[0]
        mod = sys.modules[top_level_name]
        if mod is None:
            raise ImportError
        return mod
    import_args = name, globals, locals, fromlist, level
    if DEBUG_IMPORTS:
        DEBUG_NAMES += [name]
        print(DEBUG_NAMES, end='\r\n')
    result = None
    if level > 0:
        caller_mod_path = tuple(sys._current_frames().values())[0].f_back.f_globals[
            "__name__"
        ]
        for item in fromlist:
            item_path = f"{caller_mod_path}.{item}"
            if diverted(item_path):
                __myimport__(f"{caller_mod_path}.{item}", globals, locals)
            result = real_import(name, globals, locals, (item,), level)
    if result is None and (
        "*" in fromlist
        or not diverted(name)
    ):
        result = real_import(*import_args)
    # see https://docs.python.org/3/library/functions.html#import__
    if result is None and len(fromlist) > 0:
        found, o = __get_dummy_module__(name)
        for attr_name in fromlist:
            attr_o = Dummy()
            setattr(o, attr_name, attr_o)
        if not found:
            sys.modules[name] = o
        result = o
    if result is None:
        mod_path = name
        child_mod = __get_dummy_module__(mod_path)
        while True:
            if "." not in mod_path:
                break
            mod_parent_path, mod_name = mod_path.rsplit(".", maxsplit=1)
            found, parent_mod = __get_dummy_module__(mod_parent_path)
            setattr(parent_mod, mod_name, child_mod)
            if not found:
                sys.modules[mod_parent_path] = parent_mod
            # prepare next loop
            child_mod = parent_mod
            mod_path = mod_parent_path
        result = child_mod
    if DEBUG_IMPORTS:
        DEBUG_NAMES = DEBUG_NAMES[:-1]
    return result


import_children = []


def divert_unused_plumbum_modules():
    global real_import
    saved_import = __import__
    if PROFILE_IMPORTS:
        from time import time

        min_import_delay_us = os.environ.get('PROFILE_IMPORTS_MIN_DELAY_US', 500)
        min_import_delay_s = min_import_delay_us / 1000000

        def debug_import(*import_args):
            global import_children
            name = import_args[0]
            args = import_args[3:]
            children = []
            prev_import_children = import_children
            import_children = children
            t0 = time()
            res = saved_import(*import_args)
            t1 = time()
            import_children = prev_import_children
            import_children.append((t1-t0, name, args, children))
            return res

        def treemap_data(parent_name, import_children, found_names):
            data = []
            for import_child in import_children:
                delay, name, args, children = import_child
                if name in found_names:
                    continue
                else:
                    found_names.add(name)
                # children_overall_time = sum((c[0] for c in children))
                # time_outside_children = delay - children_overall_time
                # data.append((name, parent_name, time_outside_children))
                data.append((name, parent_name, delay))
                data += treemap_data(name, children, found_names)
            return data

        def abbrev_name(name):
            if len(name) > 17:
                return f'{name[0]}..{name[-15:]}'
            else:
                return name

        def print_debug_imports():
            global real_import
            # restore real import
            real_import = saved_import
            print()
            print("PROFILE_IMPORTS mode:")
            print("Generating treemap image file imports.pdf")
            try:
                import plotly.graph_objects as go
            except Exception:
                print('Sorry, PROFILE_IMPORTS mode requires more modules:')
                print('pip install plotly pandas kaleido')
                return
            data = treemap_data("", import_children, set())
            data = [(f"{abbrev_name(name)} {v*1000:.1f}ms",
                     name, parent, v)
                    for name, parent, v in data if v >= min_import_delay_s]
            data = list(zip(*data))
            fig = go.Figure(go.Treemap(
                    labels=data[0],
                    ids=data[1],
                    parents=data[2],
                    values=data[3],
                    branchvalues="total",
                    root_color="lightgrey",
                    # color_discrete_map={'(?)': 'lightgrey'},
                )
            )
            fig.update_traces(
                    marker_colorscale=['lightgrey']*len(data[0]),
            )
            fig.write_image("imports.pdf")
            print("File imports.pdf successfully generated.")

        real_import = debug_import
        atexit.register(print_debug_imports)
    else:
        real_import = saved_import
    builtins.__import__ = __myimport__


# -- Run exerything --
# --------------------
def run():
    register_faster_exit()
    fix_plumbum_locale()
    cache_modules_on_faster_disk()
    divert_unused_plumbum_modules()


run()
