from setuptools import setup, find_packages
setup(
    name = "walt-server",
    version = "0.1",
    packages = find_packages(),
    install_requires = ['rpyc>=3.3','plumbum>=1.4.2'],

    # metadata for upload to PyPI
    author = "Etienne Duble",
    author_email = "etienne.duble@imag.fr",
    description = "WalT (Wireless Testbed) control tool.",
    license = "LGPL",
    keywords = "WalT wireless testbed",
    url = "http://walt.forge.imag.fr/",

    namespace_packages = ['walt'],
    entry_points = {
        'console_scripts': [
            'walt-server = walt.server.server:run'
        ]
    },
)

