from walt.client import myhelp
from walt.common.versions import API_VERSIONING
from walt.client.link import ClientToServerLink

myhelp.register_topic('compatibility', """
The WalT servers, clients and images may be installed at different points in time, and
thus may not be compatible.
WalT knows which versions are compatible and which versions are not, and provides
means to overcome incompatibilities.

Client vs server compatibility
------------------------------

The walt command line tool will automatically upgrade or downgrade itself in order to
to communicate properly with a given WalT server. (1)

Image vs server compatibility
-----------------------------

If the WalT software embedded in an image (2) is not compatible with the server, an error message
indicates the problem when the user tries to deploy it.

The user may overcome this by using one of these two commands:
$ walt image update <image>
or
$ walt server update --ref <image>

Most of the time, one will use the image update option.
Note: in rare cases, when downgrading an image to match an older server, issues might arise:
the user scripts embedded in the image might rely on new WalT features, and these features
will not be available anymore after the downgrade. In this case, the scripts should be adapted.

The server update option is useful when one wants to test thoroughly the reproducibility of a past
experiment. It allows to rewind the WalT platform software stack to the point in time when this
experiment was first run.

Notes
-----

(1) When a user installs the walt command line tool, he gets the newest version. Thus, at first run,
the tool will have to auto-downgrade itself to match the version of the older WalT server.
Users may also want to use two (or more...) WalT platforms, e.g. one for debugging and one for
large scale experiments, and these two platforms may have different versions. In this case, the
tool will upgrade / downgrade itself each time the user switches from one platform to the other.

(2) There is a thin software layer in all WalT images. It provides means to manage WalT logs
(walt-monitor, walt-echo tools and related software) and provides a lightweight API (e.g.
make a LED blink on node, etc.)

""")

# use DEBUG_WITH_TESTPYPI=1 walt <args>
# to debug the client update feature using testpypi.python.org instead
# of the regular pypi repository.

def client_update():
    updated = False
    with ClientToServerLink() as server:
        server_cs_api = server.get_remote_api_version()
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

