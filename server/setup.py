from setuptools import setup, find_packages
setup(
    name = "walt-server",
    version = "0.4",
    packages = find_packages(),
    install_requires = ['rpyc>=3.3','plumbum>=1.4.2','walt-common',
                    'ipaddress>=1.0.7','requests>=2.3.0',
                    'docker-py>=1.2.2'],

    # metadata for upload to PyPI
    author = "Etienne Duble",
    author_email = "etienne.duble@imag.fr",
    description = "WalT (Wireless Testbed) server daemon.",
    license = "LGPL",
    keywords = "WalT wireless testbed",
    url = "http://walt.forge.imag.fr/",

    namespace_packages = ['walt'],
    entry_points = {
        'console_scripts': [
            'walt-server-daemon = walt.server.daemon:run'
        ]
    },
)

