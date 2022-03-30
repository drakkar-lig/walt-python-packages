#!/usr/bin/env python
import snimpy.mib, snimpy.manager, os.path
from pkg_resources import resource_filename

PATH_SET = False

def load_mib(mib):
    global PATH_SET
    if not PATH_SET:
        # add this directory to MIB path
        this_file = resource_filename(__name__, '__init__.py')
        this_dir = os.path.dirname(this_file)
        mib_path = snimpy.mib.path() + ':' + this_dir
        snimpy.mib.path(mib_path)
        PATH_SET = True
    if not mib in snimpy.manager.loaded:
        snimpy.manager.load(mib)

def unload_mib(mib):
    snimpy.manager.loaded.remove(mib)

def get_loaded_mibs():
    return snimpy.manager.loaded

def unload_any_of_these_mibs(mibs):
    for mib in mibs:
        if mib in snimpy.manager.loaded:
            unload_mib(mib)
