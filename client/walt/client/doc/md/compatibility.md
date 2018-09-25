
# Compatibility notes

The WalT servers and clients may be installed at different points in time, and thus may not be compatible.
However, the walt command line tool will automatically upgrade or downgrade itself in order to to communicate properly with a given WalT server.


Note that when a user installs the walt command line tool, he gets the newest version. Thus, at first run, the tool will have to auto-downgrade itself to match the version of the older WalT server. Users may also want to use two (or more...) WalT platforms, e.g. one for debugging and one for large scale experiments, and these two platforms may have different versions. In this case, the tool will upgrade / downgrade itself each time the user switches from one platform to the other.
