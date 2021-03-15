PACKAGE_GENERIC_INFO = dict(
    # metadata for upload to PyPI
    author = "WalT developers",
    author_email = "walt-contact@univ-grenoble-alpes.fr",
    license = "3-Clause BSD",
    keywords = "WalT testbed",
    url = "https://walt-project.liglab.fr"
)

PACKAGE_SPECIFIC_INFO = {
    "walt-client": dict(
        subdir = 'client',
        requires = [ 'plumbum>=1.4.2', 'commonmark>=0.7.5',
                     'pygments>=2.2.0', 'walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT control tool.",
            entry_points = {
                'console_scripts': [
                    'walt = walt.client.client:run'
                ]
            },
            data_files = [
                ('/etc/bash_completion.d', ['bash_completion/walt'])
            ],
            include_package_data = True
        )
    ),
    "walt-node": dict(
        subdir = 'node',
        requires = ['walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT optional software embedded in images.",
            entry_points = {
                'console_scripts': [
                    'walt-setup-systemd = walt.node.setup.systemd:run',
                    'walt-serial-autolog = walt.node.serial.autolog:run',
                    'walt-logs-daemon = walt.node.logs.daemon:run',
                    'walt-ipxe-kexec-reboot = walt.node.ipxekexec:run'
                ]
            },
            scripts = [ 'sh/walt-log-monitor', 'sh/walt-monitor' ],
            include_package_data = True
        )
    ),
    "walt-server": dict(
        subdir = 'server',
        requires = [    'plumbum>=1.4.2', 'snimpy>=0.8.3',
                        'pysnmp>=4.4.12',
                        'ipaddress>=1.0.7','requests>=2.21.0',
                        'sdnotify>=0.3.0',
                        'python-dateutil>=2.4.2',
                        'psycopg2-binary>=2.8.2',
                        'gevent>=21.1.2',
                        'bottle>=0.12.19',
                        'walt-common==%(upload)s',
                        'walt-virtual==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT server components.",
            entry_points = {
                'console_scripts': [
                    'walt-server-setup = walt.server.setup:run',
                    'walt-server-daemon = walt.server.daemon:run',
                    'walt-server-dhcpd = walt.server.dhcpd:run',
                    'walt-dhcp-event = walt.server.dhcpevent:run',
                    'walt-net-config = walt.server.netconfig:run'
                ]
            },
            scripts = [ 'sh/walt-image-shell-helper' ],
            include_package_data = True
        )
    ),
    "walt-virtual": dict(
        subdir = 'virtual',
        requires = ['walt-common==%(upload)s', 'python-daemon>=2.2.3'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT components related to virtualization.",
            entry_points = {
                'console_scripts': [
                    'walt-virtual-setup = walt.virtual.setup:run',
                    'walt-virtual-node = walt.virtual.node:run',
                    'walt-vpn-server = walt.virtual.vpn.server:run',
                    'walt-vpn-endpoint = walt.virtual.vpn.endpoint:run',
                    'walt-vpn-client = walt.virtual.vpn.client:vpn_client',
                    'walt-vpn-setup-credentials = walt.virtual.vpn.client:vpn_setup_credentials',
                    'walt-vpn-ssh-helper = walt.virtual.vpn.ssh:helper',
                    'walt-vpn-auth-tool = walt.virtual.vpn.authtool:run'
                ]
            },
            include_package_data = True
        )
    ),
    "walt-common": dict(
        subdir = 'common',
        requires = ['plumbum>=1.4.2','requests>=2.21.0'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT common python modules."
        )
    )
}

