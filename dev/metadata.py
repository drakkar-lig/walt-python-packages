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
        requires = [ 'plumbum>=1.7.2', 'commonmark>=0.7.5',
                     'pygments>=2.2.0', 'walt-common==%(upload)s'],
        extras_require = {
            'g5k': [ 'walt-client-g5k==%(upload)s' ]
        },
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT control tool.",
            entry_points = {
                'console_scripts': [
                    'walt = walt.client.client:run',
                    'walt-autocomplete-helper = walt.client.autocomplete.helper:autocomplete_helper'
                ]
            },
            data_files = [
                ('/etc/bash_completion.d', ['bash_completion/walt'])
            ],
            include_package_data = True
        )
    ),
    "walt-client-g5k": dict(
        subdir = 'client-g5k',
        requires = [ 'execo>=2.6.5', 'walt-client==%(upload)s' ],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT control tool -- Grid'5000 plugin.",
            entry_points = {
                'console_scripts': [
                    'walt-g5k-deploy-helper = walt.client.g5k.deploy.helper:run'
                ]
            },
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
                    'walt-node-setup = walt.node.setup:run',
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
        requires = [    'plumbum>=1.7.2', 'snimpy>=0.8.3',
                        'pysnmp>=4.4.12',
                        'ipaddress>=1.0.7','requests>=2.21.0',
                        'sdnotify>=0.3.0',
                        'psycopg2-binary>=2.8.2',
                        'gevent>=21.1.2',
                        'bottle>=0.12.19',
                        'aiohttp>=3.8.1',
                        'aiostream>=0.4.4',
                        'walt-common==%(upload)s',
                        'walt-virtual==%(upload)s',
                        'walt-vpn==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT server components.",
            entry_points = {
                'console_scripts': [
                    'walt-server-setup = walt.server.setup:run',
                    'walt-server-daemon = walt.server.daemon:run',
                    'walt-server-httpd = walt.server.httpd:run',
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
        requires = ['walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT components related to virtualization.",
            entry_points = {
                'console_scripts': [
                    'walt-virtual-setup-node = walt.virtual.setup.node:run',
                    'walt-virtual-node = walt.virtual.node:run'
                ]
            },
            scripts = [ 'sh/walt-vnode-ifup', 'sh/walt-vnode-ifdown' ],
            include_package_data = True
        )
    ),
    "walt-vpn": dict(
        subdir = 'vpn',
        requires = ['walt-common==%(upload)s', 'python-daemon>=2.2.3', 'cffi>=1.0.0'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT VPN components.",
            entry_points = {
                'console_scripts': [
                    'walt-vpn-server = walt.vpn.server:run',
                    'walt-vpn-endpoint = walt.vpn.endpoint:run',
                    'walt-vpn-client = walt.vpn.client:vpn_client',
                    'walt-vpn-setup-credentials = walt.vpn.client:vpn_setup_credentials',
                    'walt-vpn-ssh-helper = walt.vpn.ssh:helper',
                    'walt-vpn-auth-tool = walt.vpn.authtool:run',
                    'walt-vpn-setup = walt.vpn.setup:run'
                ]
            },
            setup_requires = ["cffi>=1.0.0"],
            cffi_modules = ["walt/vpn/ext/build.py:ffibuilder"],
            include_package_data = True
        )
    ),
    "walt-common": dict(
        subdir = 'common',
        requires = ['plumbum>=1.7.2','requests>=2.21.0', 'python-dateutil>=2.8.1'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT common python modules."
        )
    )
}

