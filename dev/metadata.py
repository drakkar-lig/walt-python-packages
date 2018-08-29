PACKAGE_GENERIC_INFO = dict(
    # metadata for upload to PyPI
    author = "Etienne Duble",
    author_email = "etienne.duble@imag.fr",
    license = "LGPL",
    keywords = "WalT wireless testbed",
    url = "http://walt.forge.imag.fr/",
    namespace_packages = ['walt']
)

PACKAGE_SPECIFIC_INFO = {
    "walt-client": dict(
        subdir = 'client',
        requires = ['plumbum>=1.4.2','walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) control tool.",
            entry_points = {
                'console_scripts': [
                    'walt = walt.client.client:run'
                ]
            },
            data_files = [
                ('/etc/bash_completion.d', ['bash_completion/walt'])
            ]
        )
    ),
    "walt-node": dict(
        subdir = 'node',
        requires = ['walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) software embedded in images.",
            entry_points = {
                'console_scripts': [
                    'walt-setup-systemd = walt.node.setup.systemd:run',
                    'walt-serial-autolog = walt.node.serial.autolog:run',
                    'walt-logs-daemon = walt.node.logs.daemon:run'
                ]
            },
            scripts = [ 'sh/walt-monitor', 'sh/walt-echo' ],
            include_package_data = True
        )
    ),
    "walt-server": dict(
        subdir = 'server',
        requires = [    'plumbum>=1.4.2', 'snimpy>=0.8.3',
                        'ipaddress>=1.0.7','requests>=2.3.0',
                        'docker-py>=1.2.2','sdnotify>=0.3.0',
                        'python-dateutil>=2.4.2',
                        'walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) server daemon.",
            entry_points = {
                'console_scripts': [
                    'walt-server-daemon = walt.server.daemon:run',
                    'walt-server-console = walt.server.ui.console:run',
                    'walt-dhcp-event = walt.server.dhcpevent:run',
                    'walt-net-config = walt.server.netconfig:run',
                    'walt-fake-ipxe-node = walt.server.fakeipxenode:run'
                ]
            },
            include_package_data = True
        )
    ),
    "walt-common": dict(
        subdir = 'common',
        requires = ['plumbum>=1.4.2'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) common python modules."
        )
    ),
    "walt-clientselector": dict(
        subdir = 'clientselector',
        requires = [ 'walt-client==%(upload)s' ],
        version_str = '%(cs_api)s.%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) virtual package for walt-client update."
        )
    ),
    "walt-nodeselector": dict(
        subdir = 'nodeselector',
        requires = [ 'walt-node==%(upload)s' ],
        version_str = '%(ns_api)s.%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) virtual package for walt-node update."
        )
    )
}

