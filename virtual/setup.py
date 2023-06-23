# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-virtual",
    "version": "8.0",
    "install_requires": ["walt-common==8.0"],
    "author": "WalT developers",
    "author_email": "walt-contact@univ-grenoble-alpes.fr",
    "keywords": "WalT testbed",
    "license": "3-Clause BSD",
    "url": "https://walt-project.liglab.fr",
    "description": "WalT components related to virtualization.",
    "entry_points": {
        "console_scripts": [
            "walt-virtual-setup-node = walt.virtual.setup.node:run",
            "walt-virtual-node = walt.virtual.node:run",
        ]
    },
    "include_package_data": True,
}
setup_info.update(packages=find_packages())
setup(**setup_info)
