PACKAGE_GENERIC_INFO = dict(
    # metadata for upload to PyPI
    author="WalT developers",
    author_email="walt-contact@univ-grenoble-alpes.fr",
    license="3-Clause BSD",
    keywords="WalT testbed",
    url="https://walt-project.liglab.fr",
)

PACKAGE_SPECIFIC_INFO = {
    "walt-doc": dict(
        subdir="doc",
        requires=[
            "commonmark>=0.7.5",
            "pygments>=2.2.0",
            "setuptools>=70.0.0",   # includes pkg_resources, for finding md files
            "walt-common==%(walt_version)s",
        ],
        version_str="%(walt_version)s",
        setup=dict(
            description="WalT doc files and related code.",
            include_package_data=True,
        ),
    ),
    "walt-client": dict(
        subdir="client",
        requires=[
            "plumbum>=1.7.2",
            "walt-common==%(walt_version)s",
            "walt-doc==%(walt_version)s",
        ],
        extras_require={"g5k": ["walt-client-g5k==%(walt_version)s"]},
        version_str="%(walt_version)s",
        setup=dict(
            description="WalT control tool.",
            entry_points={
                "console_scripts": [
                    "walt = walt.client.client:run",
                    "walt-autocomplete-helper = walt.client.autocomplete:ac_helper",
                ]
            },
        ),
    ),
    "walt-client-g5k": dict(
        subdir="client-g5k",
        requires=["execo>=2.6.5", "walt-client==%(walt_version)s"],
        version_str="%(walt_version)s",
        setup=dict(
            description="WalT control tool -- Grid'5000 plugin.",
            entry_points={
                "console_scripts": [
                    "walt-g5k-deploy-helper = walt.client.g5k.deploy.helper:run"
                ]
            },
        ),
    ),
    "walt-node": dict(
        subdir="node",
        requires=["walt-common==%(walt_version)s"],
        version_str="%(walt_version)s",
        setup=dict(
            description="WalT optional software embedded in images.",
            entry_points={
                "console_scripts": [
                    "walt-node-setup = walt.node.setup:run",
                    "walt-serial-autolog = walt.node.serial.autolog:run",
                    "walt-logs-daemon = walt.node.logs.daemon:run",
                    "walt-ipxe-kexec-reboot = walt.node.ipxekexec:run",
                ]
            },
            scripts=["sh/walt-log-monitor", "sh/walt-monitor"],
            include_package_data=True,
        ),
    ),
    "walt-server": dict(
        subdir="server",
        requires=[
            "python-apt-binary",  # https://github.com/drakkar-lig/python-apt-binary
            "plumbum>=1.7.2",
            "snimpy>=1.0.3",
            "ipaddress>=1.0.7",
            "requests>=2.21.0",
            "sdnotify>=0.3.0",
            "psycopg2-binary>=2.8.2",
            "gevent>=21.1.2",
            "bottle>=0.12.19",
            "aiohttp>=3.10.11",
            "aiostream>=0.4.4",
            "netifaces>=0.11.0",
            "podman>=4.2.0",
            "setproctitle>=1.3.2",
            "numpy>=1.24.3",
            "numba>=0.58.1",
            "cffi>=1.16.0",
            "dnspython>=2.7.0",
            "walt-client==%(walt_version)s",
            "walt-common==%(walt_version)s",
            "walt-doc==%(walt_version)s",
            "walt-virtual==%(walt_version)s",
        ],
        version_str="%(walt_version)s",
        setup=dict(
            description="WalT server components.",
            entry_points={
                "console_scripts": [
                    "walt-server-setup = walt.server.setup.main:run",
                    "walt-server-daemon = walt.server.daemon:run",
                    "walt-server-httpd = walt.server.services.httpd:run",
                    "walt-server-tftpd = walt.server.services.tftpd:run",
                    "walt-server-snmpd = walt.server.services.snmpd:run",
                    "walt-server-lldpd = walt.server.services.lldpd:run",
                    "walt-server-ptpd = walt.server.services.ptpd:run",
                    "walt-server-nbd = walt.server.services.nbd:run",
                    "walt-server-trackexec-replay = walt.server.trackexec.player:run",
                    "walt-server-trackexec-analyse = walt.server.trackexec.analyse:run",
                    "walt-dhcp-event = walt.server.dhcpevent:run",
                    "walt-net-config = walt.server.netconfig:run",
                    "walt-image-check = walt.server.imagecheck:run",
                    "walt-annotate-cmd = walt.server.annotatecmd:run",
                    "walt-image-mount = walt.server.mount.mount:run",
                    "walt-image-umount = walt.server.mount.umount:run",
                    "walt-set-poe = walt.server.snmp.run:walt_set_poe",
                    "walt-server-vpn = walt.server.services.vpn:run",
                    "walt-server-vpn-endpoint = walt.server.vpn.endpoint:run",
                    "walt-vpn-admin = walt.server.vpn.admin:run",
                ]
            },
            scripts=["sh/walt-image-shell-helper",
                     "sh/walt-image-build-helper",
                     "sh/walt-image-fs-helper",
                     "sh/walt-server-cleanup",
                     "sh/walt-device-ssh",
                     "sh/walt-server-vpn-test-ssh-entrypoint"],
            setup_requires=["cffi>=1.16.0"],
            cffi_modules=["walt/server/ext/build.py:ffibuilder"],
            include_package_data=True,
        ),
    ),
    "walt-virtual": dict(
        subdir="virtual",
        requires=["walt-common==%(walt_version)s"],
        version_str="%(walt_version)s",
        setup=dict(
            description="WalT components related to virtualization.",
            entry_points={
                "console_scripts": [
                    "walt-virtual-setup-node = walt.virtual.setup.node:run",
                    "walt-virtual-node = walt.virtual.node:run",
                ]
            },
            include_package_data=True,
        ),
    ),
    "walt-common": dict(
        subdir="common",
        requires=[
            "plumbum>=1.7.2",
            "requests>=2.21.0",
            "python-dateutil>=2.8.1",
            "pyyaml>=5.3.1",
        ],
        version_str="%(walt_version)s",
        setup=dict(description="WalT common python modules."),
    ),
}
