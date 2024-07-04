# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-client",
    "version": "9.0",
    "install_requires": ["plumbum>=1.7.2", "walt-common==9.0", "walt-doc==9.0"],
    "extras_require": {"g5k": ["walt-client-g5k==9.0"]},
    "author": "WalT developers",
    "author_email": "walt-contact@univ-grenoble-alpes.fr",
    "keywords": "WalT testbed",
    "license": "3-Clause BSD",
    "url": "https://walt-project.liglab.fr",
    "description": "WalT control tool.",
    "entry_points": {
        "console_scripts": [
            "walt = walt.client.client:run",
            "walt-autocomplete-helper = walt.client.autocomplete:ac_helper",
        ]
    },
}
setup_info.update(packages=find_packages())
setup(**setup_info)
