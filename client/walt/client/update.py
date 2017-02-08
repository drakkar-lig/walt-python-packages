import os
from walt.client import myhelp
from walt.common.versions import API_VERSIONING
from walt.client.link import ClientToServerLink

myhelp.register_topic('compatibility', """
The WalT servers and clients may be installed at different points in time, and
thus may not be compatible.
However, the walt command line tool will automatically upgrade or downgrade
itself in order to to communicate properly with a given WalT server. (1)

Notes
-----

(1) When a user installs the walt command line tool, he gets the newest version. Thus, at first run,
the tool will have to auto-downgrade itself to match the version of the older WalT server.
Users may also want to use two (or more...) WalT platforms, e.g. one for debugging and one for
large scale experiments, and these two platforms may have different versions. In this case, the
tool will upgrade / downgrade itself each time the user switches from one platform to the other.

""")

# use DEBUG_WITH_TESTPYPI=1 walt <args>
# to debug the client update feature using testpypi.python.org instead
# of the regular pypi repository.

def client_update():
    updated = False
    with ClientToServerLink() as server:
        server_cs_api = server.get_api_version()
        client_cs_api = API_VERSIONING['CSAPI'][0]
        if server_cs_api != client_cs_api:
            print('Auto-updating the client to match server API...')
            if os.getenv('DEBUG_WITH_TESTPYPI'):
                repo_option = '-i https://testpypi.python.org/simple'
            else:
                repo_option = ''
            do('sudo pip install %s --upgrade "walt-clientselector==%d.*"' % \
                            (repo_option, server_cs_api))
            updated = True
    return updated

