# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-common",
    "version": "8.2",
    "install_requires": [
        "plumbum>=1.7.2",
        "requests>=2.21.0",
        "python-dateutil>=2.8.1",
        "pyyaml>=5.3.1",
    ],
    "author": "WalT developers",
    "author_email": "walt-contact@univ-grenoble-alpes.fr",
    "keywords": "WalT testbed",
    "license": "3-Clause BSD",
    "url": "https://walt-project.liglab.fr",
    "description": "WalT common python modules.",
}

from pathlib import Path

p = Path(".")

packages = set()

# we use this "finder" function to find packages in directory instead of:
# * find_packages: because find_packages obliges to specify __init__ files
# * find_namespace_packages: because it includes all subdirs, even those doesn't containing any python files
# * TODO: find an option/parameter to find_namespace_packages to do this without having to implement our own function as we are doing


def finder(path):
    if path.is_dir():
        res = False
        for p in path.iterdir():
            res = finder(p)
            if res:
                packages.add(str(path).replace("/", "."))
        return res
    else:
        if str(path).endswith(".py"):
            return True


finder(p)
packages.remove(".")

setup_info.update(packages=list(packages))
setup(**setup_info)
