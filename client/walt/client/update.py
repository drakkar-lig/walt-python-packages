from walt.common.version import __version__


class WalTUpdatedException(Exception):
    pass


def check_update(server):
    remote_version = str(server.get_remote_version())
    if remote_version != str(__version__):
        print()
        print("WALT version is different on client and on server.")
        try:
            wheels_info = server.get_client_install_wheels()
        except Exception:
            print("And server code is too old to support client auto-upgrade, sorry.")
            print("Exiting.")
            sys.exit(1)
        print("Auto-upgrading this client code to match the server version...")
        print()
        import importlib
        import os
        import subprocess
        import sys
        import tempfile
        from pathlib import Path
        pip_install = f"{sys.prefix}/bin/pip install"
        subprocess.run(f"{pip_install} --upgrade pip".split(), check=True)
        with tempfile.TemporaryDirectory() as tmpdirname:
            tmpdir = Path(tmpdirname)
            update_cmd = f"{pip_install} --upgrade"
            for whl_name, whl_content in wheels_info.items():
                whl_file = tmpdir / whl_name
                whl_file.write_bytes(whl_content)
                update_cmd += f" {whl_file}"
            subprocess.run(update_cmd.split(), check=True)
        print()
        if Path(sys.argv[0]).name == 'walt':
            # walt cli, restart the whole process
            os.execv(sys.argv[0], sys.argv)
        else:
            # Other python program, probably using the walt python api;
            # We cannot just restart the process because the script
            # may have started doing things already, before we got here.
            # Let's just reload walt modules and raise an exception.
            mod_info = dict(sys.modules.items())  # copy
            for modname, mod in mod_info.items():
                if modname.startswith('walt.'):
                    importlib.reload(mod)
            raise WalTUpdatedException
