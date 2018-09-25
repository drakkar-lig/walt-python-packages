import os
from walt.common.versions import API_VERSIONING
from walt.client.link import ClientToServerLink

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

