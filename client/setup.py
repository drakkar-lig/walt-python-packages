# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-client",
    "version": "0.44",
    "install_requires": [
        "plumbum>=1.7.2",
        "commonmark>=0.7.5",
        "pygments>=2.2.0",
        "walt-common==0.44",
    ],
    "extras_require": {"g5k": ["walt-client-g5k==0.44"]},
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
    "include_package_data": True,
}
setup_info.update(packages=find_packages())
setup(**setup_info)
