PACKAGE_GENERIC_INFO = dict(
    # metadata for upload to PyPI
    author = "Etienne Duble",
    author_email = "etienne.duble@imag.fr",
    license = "LGPL",
    keywords = "WalT wireless testbed",
    url = "http://walt.forge.imag.fr/",
    py_modules = ['info']
)

PACKAGE_SPECIFIC_INFO = {
    "walt-client": dict(
        subdir = 'client',
        requires = ['rpyc>=3.3','plumbum>=1.4.2','walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) control tool.",
            namespace_packages = ['walt'],
            entry_points = {
                'console_scripts': [
                    'walt = walt.client.client:run'
                ]
            }
        )
    ),
    "walt-node": dict(
        subdir = 'node',
        requires = ['rpyc>=3.3','plumbum>=1.4.2','walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) software embedded in images.",
            namespace_packages = ['walt'],
            entry_points = {
                'console_scripts': [
                    'walt-node-daemon = walt.node.daemon:run',
                    'walt-node-install = walt.node.install:run',
                    'walt-node-versioning-getnumbers = walt.node.versioning:getnumbers',
                    'walt-serial-autolog = walt.node.serial.autolog:run'
                ]
            },
            scripts = [ 'sh/walt-monitor', 'sh/walt-echo' ]
        )
    ),
    "walt-server": dict(
        subdir = 'server',
        requires = [
                        'rpyc>=3.3','plumbum>=1.4.2',
                        'ipaddress>=1.0.7','requests>=2.3.0',
                        'docker-py>=1.2.2','sdnotify>=0.3.0',
                        'walt-common==%(upload)s'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) server daemon.",
            namespace_packages = ['walt'],
            entry_points = {
                'console_scripts': [
                    'walt-server-daemon = walt.server.daemon.daemon:run',
                    'walt-server-console = walt.server.ui.console:run'
                ]
            }
        )
    ),
    "walt-common": dict(
        subdir = 'common',
        requires = ['rpyc>=3.3','plumbum>=1.4.2'],
        version_str = '%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) common python modules.",
            namespace_packages = ['walt']
        )
    ),
    "walt-client-selector": dict(
        subdir = 'client-selector',
        requires = [ 'walt-client==%(upload)s' ],
        version_str = '%(cs_api)s.%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) virtual package for walt-client update."
        )
    ),
    "walt-node-selector": dict(
        subdir = 'node-selector',
        requires = [ 'walt-node==%(upload)s' ],
        version_str = '%(ns_api)s.%(upload)s',
        setup = dict(
            description = "WalT (Wireless Testbed) virtual package for walt-node update."
        )
    )
}

