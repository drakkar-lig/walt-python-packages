import os, subprocess
from walt.common.version import __version__
from walt.common.tools import restart

# use DEBUG_WITH_TESTPYPI=1 <command>
# to debug the update feature using testpypi.python.org instead
# of the regular pypi repository.

def check_auto_update(server, package_name):
    updated = False
    remote_version = server.get_remote_version()
    if remote_version != int(__version__):
        print('Auto-updating software to match server API...')
        if os.getenv('DEBUG_WITH_TESTPYPI'):
            repo_option = '-i https://testpypi.python.org/simple'
        else:
            repo_option = ''
        cmd = 'sudo pip install %(repo_option)s --upgrade "%(package_name)s==%(remote_version)d"' % \
                        dict(repo_option = repo_option,
                             remote_version = remote_version,
                             package_name = package_name)
        try:
            if subprocess.call(cmd, shell=True) == 0:
                updated = True
        except BaseException as e:
            print('Issue: ' + str(e))
        if not updated:
            print('WARNING!! software update failed. Trying to continue...')
    if updated:
        restart()
    return updated

