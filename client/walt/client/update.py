import os, subprocess
from walt.common.version import __version__
from walt.client.link import ClientToServerLink

# use DEBUG_WITH_TESTPYPI=1 walt <args>
# to debug the client update feature using testpypi.python.org instead
# of the regular pypi repository.

def client_update():
    updated = False
    with ClientToServerLink() as server:
        remote_version = server.get_remote_version()
    if remote_version != int(__version__):
        print('Auto-updating the client to match server API...')
        if os.getenv('DEBUG_WITH_TESTPYPI'):
            repo_option = '-i https://testpypi.python.org/simple'
        else:
            repo_option = ''
        cmd = 'sudo pip install %s --upgrade "walt-client==%d"' % \
                        (repo_option, remote_version)
        try:
            if subprocess.call(cmd, shell=True) == 0:
                updated = True
        except BaseException as e:
            print('Issue: ' + str(e))
        if not updated:
            print('WARNING!! client update failed. Trying to continue...')
    return updated

