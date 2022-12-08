import os, sys, copy
from pathlib import Path
from string import Template
from walt.server.setup.netconf import get_default_netconf, edit_netconf_interactive, \
                                      dump_commented_netconf, same_netconfs

YAML_INDENT = 4

WALT_SERVER_CONF_PATH = Path("/etc/walt/server.conf")
WALT_SERVER_CONF_CONTENT = Template("""\
# WalT server configuration file.
# Run 'walt-server-setup --edit-conf' to update.

# network configuration
# ---------------------
network:
$indented_netconf
""")

WALT_SERVER_SPEC_PATH = Path("/etc/walt/server.spec")
WALT_SERVER_SPEC_CONTENT = """\
{
    # optional features implemented
    # -----------------------------
    "features": [ "ptp" ]
}
"""

ROOT_WALT_CONFIG_PATH = Path("/root/.walt/config")
SKEL_WALT_CONFIG_PATH = Path("/etc/skel/.walt/config")
LOCAL_WALT_CONFIG_CONTENT = """\
# WalT configuration file
# ***********************

# ip or hostname of walt server
# -----------------------------
server: localhost
"""

def get_current_conf():
    try:
        from walt.server import conf
        return conf
    except:
        return None

def edit_conf_tty_error():
    print('Sorry, cannot run server configuration editor because STDOUT is not a terminal.')
    print('Exiting.')
    sys.exit(1)

def edit_conf_keep():
    conf = get_current_conf()
    if conf is None:
        print('WARNING: Failed to load current configuration at /etc/walt/server.conf!')
        print('WARNING: Falling back to a default configuration.')
        conf = edit_conf_set_default()
    return conf

def edit_conf_set_default():
    # verify we will not overwrite an existing conf
    conf = get_current_conf()
    if conf is None:
        # this was actually expected
        return { 'network': get_default_netconf() }
    else:
        print('Note: found valid yaml file at /etc/walt/server.conf, keeping it.')
        return conf

def edit_conf_interactive():
    conf = get_current_conf()
    if conf is None:
        netconf = None
    else:
        netconf = conf['network']
    netconf = edit_netconf_interactive(netconf)
    conf = copy.deepcopy(conf) # copy
    conf['network'] = netconf # update network conf
    return conf

def define_server_conf(mode, opt_edit_conf):
    selector = (os.isatty(1), mode, opt_edit_conf)
    edit_conf_mode = {
        (True, 'image-install', True): 'interactive',
        (True, 'install', True): 'interactive',
        (True, 'upgrade', True): 'interactive',
        (True, 'image-install', False): 'set_default',
        (True, 'install', False): 'interactive',
        (True, 'upgrade', False): 'keep',
        (False, 'image-install', True): 'tty_error',
        (False, 'install', True): 'tty_error',
        (False, 'upgrade', True): 'tty_error',
        (False, 'image-install', False): 'set_default',
        (False, 'install', False): 'set_default',
        (False, 'upgrade', False): 'keep',
    }[selector]
    func = globals().get(f'edit_conf_{edit_conf_mode}')
    return func()

def same_confs(c1, c2):
    if c1 is None or c2 is None or 'network' not in c1 or 'network' not in c2:
        return False
    return same_netconfs(c1['network'], c2['network'])

def update_server_conf(conf):
    if same_confs(get_current_conf(), conf):
        return
    print(f'Saving configuration at {WALT_SERVER_CONF_PATH}... ', end='')
    commented_netconf = dump_commented_netconf(conf['network'], YAML_INDENT)
    indent = YAML_INDENT * ' '
    indented_netconf = '\n'.join((indent + l) for l in commented_netconf.splitlines())
    content = WALT_SERVER_CONF_CONTENT.substitute(indented_netconf=indented_netconf)
    WALT_SERVER_CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    WALT_SERVER_CONF_PATH.write_text(content)
    print('done')

def fix_other_conf_files():
    for path, content in ((WALT_SERVER_SPEC_PATH, WALT_SERVER_SPEC_CONTENT),
                          (ROOT_WALT_CONFIG_PATH, LOCAL_WALT_CONFIG_CONTENT),
                          (SKEL_WALT_CONFIG_PATH, LOCAL_WALT_CONFIG_CONTENT)):
        if not path.exists():
            print(f'Writing {path}... ', end=''); sys.stdout.flush()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print('done')

def setup_default_server_conf():
    print(f'Writing default conf at {WALT_SERVER_CONF_PATH}... ', end=''); sys.stdout.flush()
    configure_server_conf('virtual')
    print('done')
