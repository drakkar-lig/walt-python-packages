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
                    'walt-logs-daemon = walt.node.logs.daemon:run'
                ]
            },
            scripts = [ 'sh/walt-monitor' ],
            include_package_data = True
        )
    ),
    "walt-server": dict(
        subdir = 'server',
        requires = [    'plumbum>=1.4.2', 'snimpy>=0.8.3',
                        'ipaddress>=1.0.7','requests>=2.3.0',
                        'docker-py>=1.2.2','sdnotify>=0.3.0',
                        'python-dateutil>=2.4.2',
                        'walt-common==%(upload)s',
                        'walt-virtual==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT server components.",
            entry_points = {
                'console_scripts': [
                    'walt-server-daemon = walt.server.daemon:run',
                    'walt-server-console = walt.server.ui.console:run',
                    'walt-dhcp-event = walt.server.dhcpevent:run',
                    'walt-net-config = walt.server.netconfig:run'
                ]
            },
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
                    'walt-fake-ipxe-node = walt.virtual.fakeipxenode:run'
                ]
            }
        )
    ),
    "walt-common": dict(
        subdir = 'common',
        requires = ['plumbum>=1.4.2'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT common python modules."
        )
    )
}

