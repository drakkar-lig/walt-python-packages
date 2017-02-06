from setuptools import setup, find_packages

# make sure we are executing the new info.py
execfile('walt/nodeselector/info.py')
SETUP_INFO.update(
    packages = find_packages()
)
setup(**SETUP_INFO)
