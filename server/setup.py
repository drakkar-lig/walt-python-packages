# auto-generated by dev/setup-updater.py
# using metadata from dev/metadata.py

import sys

from setuptools import find_packages, setup

if sys.version_info[0] == 2:
    sys.exit("Sorry, Python 2 is no longer supported.")

setup_info = {
    "name": "walt-server",
    "version": "8.2",
    "install_requires": [
        "aiohttp==3.9.5",
        "aiosignal==1.3.1",
        "aiostream==0.5.2",
        "attrs==23.2.0",
        "bottle==0.12.25",
        "certifi==2024.7.4",
        "cffi==1.16.0",
        "charset-normalizer==3.3.2",
        "commonmark==0.9.1",
        "cryptography==42.0.6",
        "docutils==0.20.1",
        "frozenlist==1.4.1",
        "gevent==24.2.1",
        "greenlet==3.0.3",
        "idna==3.7",
        "ipaddress==1.0.23",
        "jinja2==3.1.4",
        "llvmlite==0.42.0",
        "lockfile==0.12.2",
        "markupsafe==2.1.5",
        "multidict==6.0.5",
        "netifaces==0.11.0",
        "numba==0.59.1",
        "numpy==1.26.4",
        "plumbum==1.8.2",
        "ply==3.11",
        "podman==5.0.0",
        "psycopg2-binary==2.9.9",
        "pyasn1==0.6.0",
        "pycparser==2.22",
        "pygments==2.17.2",
        "pysmi-lextudio==1.4.3",
        "pysnmp-lextudio==5.0.34",
        "pysnmpcrypto==0.0.4",
        "python-apt-binary",
        "python-daemon==2.3.2",
        "python-dateutil==2.9.0.post0",
        "pyxdg==0.28",
        "pyyaml==6.0.1",
        "requests==2.32.2",
        "sdnotify==0.3.2",
        "setproctitle==1.3.3",
        "setuptools==66.1.1",
        "six==1.16.0",
        "snimpy==1.0.3",
        "typing-extensions==4.11.0",
        "urllib3==2.2.2",
        "walt-client==8.2",
        "walt-common==8.2",
        "walt-doc==8.2",
        "walt-virtual==8.2",
        "walt-vpn==8.2",
        "yarl==1.9.4",
        "zope.event==5.0",
        "zope.interface==6.3",
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
            "walt-server-trackexec-replay = walt.server.trackexec.player:run",
            "walt-server-trackexec-analyse = walt.server.trackexec.analyse:run",
            "walt-dhcp-event = walt.server.dhcpevent:run",
            "walt-net-config = walt.server.netconfig:run",
            "walt-image-check = walt.server.imagecheck:run",
            "walt-annotate-cmd = walt.server.annotatecmd:run",
            "walt-image-mount = walt.server.mount.mount:run",
            "walt-image-umount = walt.server.mount.umount:run",
        ]
    },
    "include_package_data": True,
    "scripts": [
        "sh/walt-image-shell-helper",
        "sh/walt-image-build-helper",
        "sh/walt-image-fs-helper",
        "sh/walt-server-cleanup",
        "sh/walt-device-ssh",
    ],
}
setup_info.update(packages=find_packages())
setup(**setup_info)
