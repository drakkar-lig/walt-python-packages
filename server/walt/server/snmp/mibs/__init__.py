#!/usr/bin/env python
import os.path

import snimpy.manager
import snimpy.mib
from importlib.resources import files

PATH_SET = False


def load_mib(mib):
    global PATH_SET
    if not PATH_SET:
        # add this directory to MIB path
        import walt.server.snmp.mibs
        this_dir = str(files(walt.server.snmp.mibs))
        mib_path = snimpy.mib.path() + ":" + this_dir
        snimpy.mib.path(mib_path)
        PATH_SET = True
    if mib not in snimpy.manager.loaded:
        snimpy.manager.load(mib)


def unload_mib(mib):
    snimpy.manager.loaded.remove(mib)


def get_loaded_mibs():
    return snimpy.manager.loaded


def unload_any_of_these_mibs(mibs):
    for mib in mibs:
        if mib in snimpy.manager.loaded:
            unload_mib(mib)
