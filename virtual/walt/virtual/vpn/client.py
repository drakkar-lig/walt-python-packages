import os, os.path, sys, shlex, struct, daemon
from daemon.pidfile import PIDLockFile
from subprocess import check_call, check_output, Popen, PIPE, TimeoutExpired, run, DEVNULL
from select import select
from walt.virtual.tools import createtap, read_n, enable_debug, debug
from walt.virtual.vpn.ssh import ssh_with_identity
from walt.common.constants import UNSECURE_ECDSA_KEYPAIR
from walt.common.logs import LoggedApplication
from pathlib import Path
from time import time, sleep

DEBUG = False

if DEBUG:
    enable_debug()

BRIDGE_INTF = "walt-net"
VPN_USER = "walt-vpn"

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
    netdir = Path('/sys/class/net')
    if netdir.is_dir():
        for intfdir in netdir.iterdir():
            if (intfdir / 'device').exists():
                # seems to be a real hardware interface
                mac = (intfdir / 'address').read_text().strip()
                print("Found mac address %s (on %s)" % (mac, intfdir.name))
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

def do_vpn_client(walt_vpn_entrypoint):
    # setup credentials if needed
    if not PRIV_KEY_FILE.exists():
        sys.exit("Run the following command once, first: 'walt-vpn-setup-credentials <walt-server>'")

    # Create TAP
    tap, tap_name = createtap()

    # create bridge
    if not (Path('/sys/class/net') / BRIDGE_INTF).exists():
        check_call('ip link add %s type bridge' % BRIDGE_INTF, shell=True)
    check_call('ip link set up dev %s' % BRIDGE_INTF, shell=True)

    # bring it up, add it to bridge
    check_call('ip link set up dev %(intf)s' % dict(intf = tap_name), shell=True)
    check_call('ip link set master ' + BRIDGE_INTF + ' dev ' + tap_name, shell=True)

    print('added ' + tap_name + ' to bridge ' + BRIDGE_INTF)

    # start loop
    if DEBUG:
        print('Running...')
        vpn_client_loop(tap, walt_vpn_entrypoint)
    else:
        print('Going to background.')
        with daemon.DaemonContext(
                    files_preserve = [tap],
                    pidfile = PIDLockFile('/var/run/walt-vpn-client.pid')):
            vpn_client_loop(tap, walt_vpn_entrypoint)

def vpn_client_loop(tap, walt_vpn_entrypoint):
    while True:
        # Start the command to connect to server
        popen = Popen(ssh_with_identity(
                    str(PRIV_KEY_FILE),
                    SSH_VPN_COMMAND.strip() % dict(
                        connect_timeout = SSH_CONNECT_TIMEOUT,
                        priv_key = str(PRIV_KEY_FILE),
                        walt_vpn_entrypoint = walt_vpn_entrypoint
                    )), stdin=PIPE, stdout=PIPE, bufsize=0)
        # transmit packets
        should_continue = packet_transmission_loop(popen, tap)
        if not should_continue:
            break

def packet_transmission_loop(popen, tap):
    # start select loop
    # we will:
    # * transfer packets coming from the tap interface to ssh stdin
    # * transfer packets coming from ssh stdout to the tap interface
    fds = [ popen.stdout, tap ]
    while True:
        r, w, e = select(fds, [], [])
        if len(r) == 0:
            break
        r_obj = r[0]
        r_fd = r_obj.fileno()
        if r_obj == tap:
            packet = os.read(r_fd, 8192)
            if len(packet) == 0:
                # unexpected, let's stop
                print(time(), 'short read on tap, exiting.')
                return False
            # encode packet length as 2 bytes
            encoded_packet_len = struct.pack('!H', len(packet))
            debug('transmitting packet of', len(packet), 'bytes from tap to ssh channel')
            fd = popen.stdin.fileno()
            os.write(fd, encoded_packet_len)
            os.write(fd, packet)
        else:
            encoded_packet_len = read_n(r_fd, 2)
            if len(encoded_packet_len) < 2:
                print(time(), 'short read on ssh channel (reading packet length), will re-init.')
                sleep(5)
                return True
            # decode 2 bytes of packet length
            packet_len = struct.unpack('!H', encoded_packet_len)[0]
            # empty packet?
            if packet_len == 0:
                raise Exception(str(time()) + ' Got packet_len of 0!')
            packet = read_n(r_fd, packet_len)
            if len(packet) < packet_len:
                print(time(), 'short read on ssh channel (reading packet), will re-init.')
                sleep(5)
                return True
            debug('transmitting packet of', packet_len, 'bytes from ssh channel to tap')
            os.write(tap.fileno(), packet)

class WalTVPNClient(LoggedApplication):
    """Establish the VPN up to walt server"""
    def main(self, walt_vpn_entrypoint):
        self.init_logs()
        do_vpn_client(walt_vpn_entrypoint)

def vpn_client():
    WalTVPNClient.run()

class WalTVPNSetupCredentials(LoggedApplication):
    """Establish VPN credentials with walt server"""
    def main(self, walt_vpn_entrypoint):
        self.init_logs()
        setup_credentials(walt_vpn_entrypoint)

def vpn_setup_credentials():
    WalTVPNSetupCredentials.run()
