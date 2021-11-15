import os, os.path, sys, shlex, struct, daemon, secrets, traceback, atexit
from daemon.pidfile import PIDLockFile
from subprocess import check_call, check_output, Popen, PIPE, TimeoutExpired, run, DEVNULL
from select import select
from walt.vpn.tools import read_n, enable_debug, debug, readline_unbuffered,               \
     create_l2tp_tunnel, remove_l2tp_tunnel, create_l2tp_interface, remove_l2tp_interface, \
     create_l2tp_socket
from walt.vpn.ssh import ssh_with_identity
from walt.vpn.const import BRIDGE_INTF
from walt.vpn.ext._loops.lib import client_transmission_loop
from walt.common.constants import UNSECURE_ECDSA_KEYPAIR
from walt.common.logs import LoggedApplication
from plumbum import cli
from pathlib import Path
from time import sleep

DEBUG = False

if DEBUG:
    enable_debug()

VPN_USER = "walt-vpn"
PID_FILE = '/var/run/walt-vpn-client.pid'

SSH_CONF_DIR = Path.home() / '.ssh'
PRIV_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_vpn'
CERT_PUB_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_vpn-cert.pub'
UNSECURE_PRIV_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_unsecure'
UNSECURE_PUB_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_unsecure.pub'

SSH_CONNECT_TIMEOUT = 10

SSH_AUTH_COMMAND = """
ssh -T -q -A \
    -o StrictHostKeyChecking=no \
    -o PreferredAuthentications=publickey \
    -o ConnectTimeout=%(connect_timeout)d \
    -i %(unsecure_priv_key)s \
    walt-vpn@%(walt_vpn_entrypoint)s %(mac_address)s
"""

SSH_VPN_COMMAND = """
ssh -T -q -A \
    -o PreferredAuthentications=publickey \
    -o ConnectTimeout=%(connect_timeout)d \
    -i %(priv_key)s \
    walt-vpn@%(walt_vpn_entrypoint)s
"""

AUTH_TIMEOUT = 60

def get_mac_address():
    routeinfo = Path('/proc/net/route')
    netdir = Path('/sys/class/net')
    if routeinfo.exists() and netdir.is_dir():
        # find interface of default route
        routes = Path('/proc/net/route').read_text()
        gw_iface = None
        for line in routes.splitlines()[1:]:
            iface, dst, gw, flags, refcnt, use, metric, mask = line.split()[:8]
            if mask == '00000000': # netmask is 0.0.0.0 => default route
                gw_iface = iface
                break
        if gw_iface is not None:
            # read its mac address
            mac = (netdir / gw_iface / 'address').read_text().strip()
            print("Found mac address %s (on %s)" % (mac, gw_iface))
            return mac
    print("Could not get mac address. Failed.", file=sys.stderr)
    sys.exit()

def setup_credentials(walt_vpn_entrypoint):
    if PRIV_KEY_FILE.exists():
        print('Credentials are already setup.')
        sys.exit()
    mac_address = get_mac_address()
    if not SSH_CONF_DIR.is_dir():
        SSH_CONF_DIR.mkdir()
    if not UNSECURE_PRIV_KEY_FILE.exists():
        UNSECURE_PRIV_KEY_FILE.write_text(UNSECURE_ECDSA_KEYPAIR['openssh-priv'])
        UNSECURE_PRIV_KEY_FILE.chmod(0o600)
    if not UNSECURE_PUB_KEY_FILE.exists():
        UNSECURE_PUB_KEY_FILE.write_text(UNSECURE_ECDSA_KEYPAIR['openssh-pub'])
    while True:
        try:
            cred_info = check_output(ssh_with_identity(
                    str(UNSECURE_PRIV_KEY_FILE),
                    SSH_AUTH_COMMAND.strip() % dict(
                        connect_timeout = SSH_CONNECT_TIMEOUT,
                        unsecure_priv_key = str(UNSECURE_PRIV_KEY_FILE),
                        walt_vpn_entrypoint = walt_vpn_entrypoint,
                        mac_address = mac_address
                    )), timeout=AUTH_TIMEOUT).decode('ascii')
        except TimeoutExpired:
            print("Connection timed out.")
            continue
        parts = cred_info.split('\n\n')
        if len(parts) < 2 or parts[0] not in ('FAILED', 'OK'):
            print("Wrong server response. Will retry shortly.")
            sleep(5)
            continue
        if parts[0] == "FAILED":
            print("Issue: %s\nWill retry in a moment." % parts[1].strip())
            sleep(15)
            continue
        # OK
        PRIV_KEY_FILE.write_text(parts[1].strip() + '\n')
        PRIV_KEY_FILE.chmod(0o600)
        CERT_PUB_KEY_FILE.write_text(parts[2].strip() + '\n')
        print('OK, new credentials obtained and saved.')
        break

def do_vpn_client(info, walt_vpn_entrypoint):
    # setup credentials if needed
    if not PRIV_KEY_FILE.exists():
        sys.exit("Run the following command once, first: 'walt-vpn-setup-credentials <walt-server>'")
    # create walt-net bridge
    if not (Path('/sys/class/net') / BRIDGE_INTF).exists():
        check_call('ip link add %s type bridge' % BRIDGE_INTF, shell=True)
    check_call('ip link set up dev %s' % BRIDGE_INTF, shell=True)
    # start loop
    if DEBUG or info.foreground:
        Path(PID_FILE).write_text("%d\n" % os.getpid())
        vpn_client_loop(walt_vpn_entrypoint)
    else:
        print('Going to background.')
        with daemon.DaemonContext(
                    files_preserve = [tap],
                    pidfile = PIDLockFile(PID_FILE)):
            vpn_client_loop(walt_vpn_entrypoint)

def parse_env_line(fd):
    env_line = readline_unbuffered(fd)
    words = env_line.split()
    if words[0] != 'ENV':
        raise Exception('Server sent: ' + env_line + '. Expected ENV line instead.')
    it = iter(words[1:])
    env = {}
    for attr in it:
        value = next(it)
        env[attr] = value
    return env

def create_virtual_interface(env):
    # create L2TP interface
    tunnel_id = env['L2TP_CLIENT_TUNNEL_ID']
    peer_tunnel_id = env['L2TP_SERVER_TUNNEL_ID']
    session_id = env['L2TP_CLIENT_SESSION_ID']
    peer_session_id = env['L2TP_SERVER_SESSION_ID']
    create_l2tp_tunnel(tunnel_id, peer_tunnel_id)
    ifname = create_l2tp_interface(tunnel_id, session_id, peer_session_id)
    return ifname

def remove_virtual_interface(env):
    tunnel_id = env['L2TP_CLIENT_TUNNEL_ID']
    session_id = env['L2TP_CLIENT_SESSION_ID']
    remove_l2tp_interface(tunnel_id, session_id)
    remove_l2tp_tunnel(tunnel_id)

def init_env():
    return dict(
        popens = [],
        ifname = None,
        udp_socket = None
    )

env = init_env()

def release_env():
    # call wait() on subprocesses
    for popen in env['popens']:
        popen.wait()
    if env['ifname'] is not None:
        remove_virtual_interface(env)
    if env['udp_socket'] is not None:
        env['udp_socket'].close()
    env.update(init_env())

def vpn_client_loop(walt_vpn_entrypoint):
    atexit.register(release_env)
    client_id = secrets.token_hex(8)
    while True:
        # Start the command to connect to server
        args = ()
        try:
            for channel_type in ('lengths', 'packets'):
                popen = Popen(ssh_with_identity(
                        str(PRIV_KEY_FILE),
                        SSH_VPN_COMMAND.strip() % dict(
                            connect_timeout = SSH_CONNECT_TIMEOUT,
                            priv_key = str(PRIV_KEY_FILE),
                            walt_vpn_entrypoint = walt_vpn_entrypoint
                        )), stdin=PIPE, stdout=PIPE, bufsize=0)
                env['popens'].append(popen)
                args += (popen.stdin.fileno(), popen.stdout.fileno())
                # server sends a line to indicate VPN protocol version
                # we ignore it since this code only handles initial version 1 for now
                readline_unbuffered(popen.stdout.fileno())
                header = f"SETUP CLIENT_ID {client_id} ENDPOINT_MODE {channel_type}\n" + \
                          "RUN\n"
                popen.stdin.write(header.encode("ASCII"))
                env.update(parse_env_line(popen.stdout.fileno()))
            env['ifname'] = create_virtual_interface(env)
            env['udp_socket'] = create_l2tp_socket()
            args += (env['udp_socket'].fileno(),)
            # transmit packets
            print()
            print('-- ready! --')
            print('now transfering packets.')
            should_continue = client_transmission_loop(*args)
        except KeyboardInterrupt:
            raise
        except:
            traceback.print_exc()
            print('Trying to reconnect in a few seconds...')
            sleep(5)
            should_continue = True
        release_env()
        if not should_continue:
            break

class WalTVPNClient(LoggedApplication):
    """Establish the VPN up to walt server"""
    foreground = cli.Flag(["f", "foreground"], help = "Run in foreground")
    def main(self, walt_vpn_entrypoint):
        self.init_logs()
        do_vpn_client(self, walt_vpn_entrypoint)

def vpn_client():
    WalTVPNClient.run()

class WalTVPNSetupCredentials(LoggedApplication):
    """Establish VPN credentials with walt server"""
    def main(self, walt_vpn_entrypoint):
        self.init_logs()
        setup_credentials(walt_vpn_entrypoint)

def vpn_setup_credentials():
    WalTVPNSetupCredentials.run()
