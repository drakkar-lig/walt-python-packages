# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-server",
    "version": "8.0",
    "install_requires": [
        "PyYAML==6.0",
        "Pygments==2.15.1",
        "aiohttp==3.8.4",
        "aiosignal==1.3.1",
        "aiostream==0.4.5",
        "async-timeout==4.0.2",
        "attrs==23.1.0",
        "bottle==0.12.25",
        "certifi==2023.5.7",
        "cffi==1.15.1",
        "charset-normalizer==3.1.0",
        "commonmark==0.9.1",
        "docutils==0.20",
        "frozenlist==1.3.3",
        "gevent==22.10.2",
        "greenlet==2.0.2",
        "idna==3.4",
        "ipaddress==1.0.23",
        "lockfile==0.12.2",
        "multidict==6.0.4",
        "netifaces==0.11.0",
        "plumbum==1.8.1",
        "ply==3.11",
        "podman==4.5.0",
        "psycopg2-binary==2.9.6",
        "pyasn1==0.4.8",
        "pycparser==2.21",
        "pycryptodomex==3.17",
        "pysmi==0.3.4",
        "pysnmp==4.4.12",
        "python-apt-binary",
        "python-daemon==2.3.2",
        "python-dateutil==2.8.2",
        "pyxdg==0.28",
        "requests==2.31.0",
        "sdnotify==0.3.2",
        "setproctitle==1.3.2",
        "setuptools==44.1.1",
        "six==1.16.0",
        "snimpy==1.0.0",
        "tomli==2.0.1",
        "urllib3==1.26.15",
        "walt-client==8.0",
        "walt-common==8.0",
        "walt-virtual==8.0",
        "walt-vpn==8.0",
        "yarl==1.9.2",
        "zope.event==4.6",
        "zope.interface==6.0",
    ],
    "author": "WalT developers",
    "author_email": "walt-contact@univ-grenoble-alpes.fr",
    "keywords": "WalT testbed",
    "license": "3-Clause BSD",
    "url": "https://walt-project.liglab.fr",
    "description": "WalT server components.",
    "entry_points": {
        "console_scripts": [
            "walt-server-setup = walt.server.setup.main:run",
            "walt-server-daemon = walt.server.daemon:run",
            "walt-server-httpd = walt.server.services.httpd:run",
            "walt-server-tftpd = walt.server.services.tftpd:run",
            "walt-server-snmpd = walt.server.services.snmpd:run",
            "walt-server-lldpd = walt.server.services.lldpd:run",
            "walt-server-ptpd = walt.server.services.ptpd:run",
            "walt-dhcp-event = walt.server.dhcpevent:run",
            "walt-net-config = walt.server.netconfig:run",
            "walt-image-check = walt.server.imagecheck:run",
            "walt-annotate-cmd = walt.server.annotatecmd:run",
        ]
    },
    "include_package_data": True,
    "scripts": ["sh/walt-image-shell-helper", "sh/walt-image-build-helper"],
}
setup_info.update(packages=find_packages())
setup(**setup_info)
