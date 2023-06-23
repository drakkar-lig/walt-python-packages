# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-client-g5k",
    "version": "8.0",
    "install_requires": ["execo>=2.6.5", "walt-client==8.0"],
    "author": "WalT developers",
    "author_email": "walt-contact@univ-grenoble-alpes.fr",
    "keywords": "WalT testbed",
    "license": "3-Clause BSD",
    "url": "https://walt-project.liglab.fr",
    "description": "WalT control tool -- Grid'5000 plugin.",
    "entry_points": {
        "console_scripts": [
            "walt-g5k-deploy-helper = walt.client.g5k.deploy.helper:run"
        ]
    },
}
setup_info.update(packages=find_packages())
setup(**setup_info)
