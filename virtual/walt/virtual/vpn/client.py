import os, os.path, sys, shlex, struct
from subprocess import check_call, check_output, Popen, PIPE, TimeoutExpired, run, DEVNULL
from select import select
from walt.virtual.tools import createtap, read_n, enable_debug, debug
from walt.common.constants import UNSECURE_ECDSA_KEYPAIR
from pathlib import Path
from time import time, sleep

DEBUG = False

if DEBUG:
    enable_debug()

BRIDGE_INTF = "walt-net"
VPN_USER = "walt-vpn"

USAGE='''\
Usage:
>> $ %(prog)s <walt-server>

Note: in order to avoid exposing walt server to the wild, <walt-server>
is usually replaced by an appropriately configured ssh proxy.
'''

SSH_CONF_DIR = Path.home() / '.ssh'
PRIV_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_vpn'
CERT_PUB_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_vpn-cert.pub'
UNSECURE_PRIV_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_unsecure'
UNSECURE_PUB_KEY_FILE = SSH_CONF_DIR / 'id_ecdsa_walt_unsecure.pub'

SSH_CONNECT_TIMEOUT = 10

SSH_AUTH_COMMAND = """
ssh -T -q -A -o StrictHostKeyChecking=no -o ConnectTimeout=%(connect_timeout)d \
    -i %(unsecure_priv_key)s \
    walt-vpn@%(walt_vpn_entrypoint)s %(mac_address)s
"""

SSH_VPN_COMMAND = """
ssh -T -q -A -o ConnectTimeout=%(connect_timeout)d \
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
            cred_info = check_output(format_ssh_command(
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
        break

# For easy management of per-command ssh identity, we always start a new ssh-agent
# (even if there is already one agent running on the system). This agent will
# be running as long a the subcommand specified is running. Since we actually
# have several things to do (2 things, see function 'ssh_helper' below), we call
# this program (i.e. walt-vpn-client) recursively, with first arg set to 'ssh-helper',
# and get to function 'ssh_helper' below.
def format_ssh_command(key_path, ssh_command):
    return shlex.split(
            "ssh-agent %(this_prog)s ssh-helper %(key_path)s %(ssh_command)s" % dict(
            this_prog = sys.argv[0],
            key_path = key_path,
            ssh_command = ssh_command
    ))

def ssh_helper(key_path, *ssh_command):
    # We add the key explicitely using ssh-add.
    # (Using ssh option "-o AddKeysToAgent=yes" on command ssh apparently does not
    # work: it only adds the key, not the certificate.)
    check_call([ 'ssh-add', key_path ], stderr=DEVNULL)
    # replace this current process with the specified ssh command
    os.execvp(ssh_command[0], ssh_command)

def run():
    # Verify args
    if len(sys.argv) < 2:
        print(USAGE % dict(prog = os.path.basename(sys.argv[0])), end='')
        sys.exit()

    # if arg is "ssh-helper", this means we were called recursively.
    if sys.argv[1] == "ssh-helper":
        return ssh_helper(*sys.argv[2:])

    # otherwise, this is the standard call.
    walt_vpn_entrypoint = sys.argv[1]

    # setup credentials if needed
    if not PRIV_KEY_FILE.exists():
        setup_credentials(walt_vpn_entrypoint)

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

    # Start the command to connect to server
    popen = Popen(format_ssh_command(
                str(PRIV_KEY_FILE),
                SSH_VPN_COMMAND.strip() % dict(
                    connect_timeout = SSH_CONNECT_TIMEOUT,
                    priv_key = str(PRIV_KEY_FILE),
                    walt_vpn_entrypoint = walt_vpn_entrypoint
                )), stdin=PIPE, stdout=PIPE, bufsize=0)

    print('Running...')
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
                break
            # encode packet length as 2 bytes
            encoded_packet_len = struct.pack('!H', len(packet))
            debug('transmitting packet of', len(packet), 'bytes from tap to ssh channel')
            fd = popen.stdin.fileno()
            os.write(fd, encoded_packet_len)
            os.write(fd, packet)
        else:
            encoded_packet_len = read_n(r_fd, 2)
            if len(encoded_packet_len) < 2:
                print(time(), 'short read on ssh channel (reading packet length), exiting.')
                break
            # decode 2 bytes of packet length
            packet_len = struct.unpack('!H', encoded_packet_len)[0]
            # empty packet?
            if packet_len == 0:
                raise Exception(str(time()) + ' Got packet_len of 0!')
            packet = read_n(r_fd, packet_len)
            if len(packet) < packet_len:
                print(time(), 'short read on ssh channel (reading packet), exiting.')
                break
            debug('transmitting packet of', packet_len, 'bytes from ssh channel to tap')
            os.write(tap.fileno(), packet)
