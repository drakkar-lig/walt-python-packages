import netifaces, time, sys
from pathlib import Path
from string import Template
from plumbum.cli.terminal import prompt
from walt.common.term import choose

WALT_DEFAULT_IP_CONF = "192.168.192.1/22"
WALT_SERVER_CONF_PATH = Path("/etc/walt/server.conf")
WALT_SERVER_VIRTUAL_CONF_CONTENT = Template("""\
# WalT server configuration file.
# Run 'walt-server-setup --edit-conf' to update.

# network configuration
# ---------------------
network:
    # platform network
    walt-net:
        raw-device: null
        ip: $ip_conf
""")
WALT_SERVER_SIMPLE_CONF_CONTENT = Template("""\
# WalT server configuration file.
# Run 'walt-server-setup --edit-conf' to update.

# network configuration
# ---------------------
network:
    # platform network
    walt-net:
        raw-device: $raw_intf
        ip: $ip_conf
""")
WALT_SERVER_VLAN_CONF_CONTENT = Template("""\
# WalT server configuration file.
# Run 'walt-server-setup --edit-conf' to update.

# network configuration
# ---------------------
network:
    # platform network
    walt-net:
        raw-device: $raw_intf
        vlan: $vlan_number
        ip: $ip_conf
""")

WALT_NETWORKING_EXPLAIN = """\
The WalT server network configuration involves:
- a regular network connection (needed when interacting with the docker hub)
- a dedicated WalT platform network (walt-net) managed by the server

Configuring the regular network connexion is out-of-scope of this automated \
WalT software configuration tool.

The WalT server can configure its WalT platform network (walt-net) in several ways:
- with a plain connection to a network interface
- with a VLAN connection to a network interface (send & receive 802.1Q-tagged packets)
- as a virtual-only platform (in this case, only virtual nodes can be registered on \
this WALT platform)
"""

MSG_NOTE_UNSURE = '''Note: if unsure, you can configure a virtual-only platform for now \
and change it later by running `walt-server-setup --edit-conf`.
'''

MSG_NOTE_RESTART = '''Note: if needed you can update this configuration later by running \
`walt-server-setup --edit-conf` \
(e.g. after a missing driver is added, or a new network adapter is plugged in).'''

WALT_SERVER_SPEC_PATH = Path("/etc/walt/server.spec")
WALT_SERVER_SPEC_CONTENT = """\
{
    # optional features implemented
    # -----------------------------
    "features": [ "ptp" ]
}
"""

ROOT_WALTRC_PATH = Path("/root/.waltrc")
SKEL_WALTRC_PATH = Path("/etc/skel/.waltrc")
LOCAL_WALTRC_CONTENT = """\
# WalT configuration file
# ***********************

# ip or hostname of walt server
# -----------------------------
server: localhost
"""

def current_server_ip_conf():
    try:
        from walt.server import conf
        return conf['network']['walt-net']['ip']
    except:
        return None

def select_server_ip_conf():
    # if server conf was already specified previously, we have to keep the same
    # IP network has before since devices are registered with their IP in db
    curr = current_server_ip_conf()
    if curr is not None:
        return curr
    else:
        return WALT_DEFAULT_IP_CONF

def get_default_gateway_interfaces():
    return set(gw_info[1] for gw_info in netifaces.gateways()['default'].values())

def iter_wired_physical_interfaces():
    for intf_dev_dir in Path('/sys/class/net').glob('*/device'):
        intf_dir = intf_dev_dir.parent
        if (intf_dir / 'wireless').exists():
            continue
        yield intf_dir.name

def configure_server_conf(setup_type, raw_intf = None, vlan_number = None):
    ip_conf = select_server_ip_conf()
    if setup_type == 'virtual':
        content = WALT_SERVER_VIRTUAL_CONF_CONTENT.substitute(ip_conf=ip_conf)
    elif setup_type == 'plain':
        content = WALT_SERVER_SIMPLE_CONF_CONTENT.substitute(raw_intf=raw_intf, ip_conf=ip_conf)
    elif setup_type == 'vlan':
        content = WALT_SERVER_VLAN_CONF_CONTENT.substitute(
                    raw_intf=raw_intf, vlan_number=vlan_number, ip_conf=ip_conf)
    WALT_SERVER_CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    WALT_SERVER_CONF_PATH.write_text(content)

def ask_server_conf():
    print()
    print(WALT_NETWORKING_EXPLAIN)
    print('Detecting wired network interfaces...')
    wired_interfaces = []
    gw_interfaces = get_default_gateway_interfaces()
    for intf in iter_wired_physical_interfaces():
        if intf in gw_interfaces:
            print(f'Ignoring {intf}, already in use as a default gateway.')
        else:
            wired_interfaces.append(intf)
    if len(wired_interfaces) == 0:
        configure_server_conf('virtual')
        print('No usable wired interface was detected on this machine.')
        print(f'Consequently walt-net has been configured for virtual-only mode in {WALT_SERVER_CONF_PATH}.')
        print('This means only virtual nodes can be registered on this WALT server.')
        print(MSG_NOTE_RESTART)
        return
    print('Found the following wired interface(s) on this machine: ' + ','.join(wired_interfaces))
    print()
    choices = {}
    for intf in wired_interfaces:
        choices[ f'Plain connection to {intf}' ] = ('plain', intf)
        choices[ f'VLAN connection to {intf} (VLAN number will be specified next)' ] = ('vlan', intf)
    choices[ 'Virtual-only platform (select this if unsure)' ] = ('virtual',)
    while True:
        raw_intf = None
        vlan_number = None
        try:
            print(MSG_NOTE_UNSURE)
            choice = choose('Please select how walt-net should be configured:', choices)
            setup_type = choice[0]
            if setup_type == 'virtual':
                break
            setup_type, raw_intf = choice
            if setup_type == 'vlan':
                try:
                    vlan_number = prompt('Please enter the VLAN number (or ^C to abort)', type=int,
                                        validator = lambda x: x >= 0)
                except KeyboardInterrupt:
                    print(); print()
                    continue
                print()
                intf = f'{raw_intf}.{vlan_number}'
                # check selected interface is not a gateway
                # (previous check was on the raw interface)
                if intf in gw_interfaces:
                    print(f'Invalid response: interface {intf} seems to be your OS default gateway.')
                    print()
                    time.sleep(1)
                    continue
            else: # plain
                break
        except KeyboardInterrupt:
            print(); print()
            continue
        break
    configure_server_conf(setup_type, raw_intf, vlan_number)
    print(f'Configuration was saved in {WALT_SERVER_CONF_PATH}.')
    print(MSG_NOTE_RESTART)

def fix_other_conf_files():
    for path, content in ((WALT_SERVER_SPEC_PATH, WALT_SERVER_SPEC_CONTENT),
                          (ROOT_WALTRC_PATH, LOCAL_WALTRC_CONTENT),
                          (SKEL_WALTRC_PATH, LOCAL_WALTRC_CONTENT)):
        if not path.exists():
            print(f'Writing {path}... ', end=''); sys.stdout.flush()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print('done')

def setup_default_server_conf():
    print(f'Writing default conf at {WALT_SERVER_CONF_PATH}... ', end=''); sys.stdout.flush()
    configure_server_conf('virtual')
    print('done')
