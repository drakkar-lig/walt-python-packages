import os
import os.path
import sys
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired, check_call, check_output
from time import sleep

import daemon
from daemon.pidfile import PIDLockFile
from plumbum import cli
from walt.common.constants import UNSECURE_ECDSA_KEYPAIR
from walt.common.logs import LoggedApplication
from walt.vpn.ext._loops.lib import client_transmission_loop
from walt.vpn.ssh import ssh_with_identity
from walt.vpn.tools import createtap, enable_debug

DEBUG = False

if DEBUG:
    enable_debug()

BRIDGE_INTF = "walt-net"
VPN_USER = "walt-vpn"
PID_FILE = "/var/run/walt-vpn-client.pid"

SSH_CONF_DIR = Path.home() / ".ssh"
PRIV_KEY_FILE = SSH_CONF_DIR / "id_ecdsa_walt_vpn"
CERT_PUB_KEY_FILE = SSH_CONF_DIR / "id_ecdsa_walt_vpn-cert.pub"
UNSECURE_PRIV_KEY_FILE = SSH_CONF_DIR / "id_ecdsa_walt_unsecure"
UNSECURE_PUB_KEY_FILE = SSH_CONF_DIR / "id_ecdsa_walt_unsecure.pub"

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
    routeinfo = Path("/proc/net/route")
    netdir = Path("/sys/class/net")
    if routeinfo.exists() and netdir.is_dir():
        # find interface of default route
        routes = Path("/proc/net/route").read_text()
        gw_iface = None
        for line in routes.splitlines()[1:]:
            iface, dst, gw, flags, refcnt, use, metric, mask = line.split()[:8]
            if mask == "00000000":  # netmask is 0.0.0.0 => default route
                gw_iface = iface
                break
        if gw_iface is not None:
            # read its mac address
            mac = (netdir / gw_iface / "address").read_text().strip()
            print("Found mac address %s (on %s)" % (mac, gw_iface))
            return mac
    print("Could not get mac address. Failed.", file=sys.stderr)
    sys.exit()


def vpn_setup_credentials(walt_vpn_entrypoint):
    if PRIV_KEY_FILE.exists():
        print("Credentials are already setup.")
        sys.exit()
    mac_address = get_mac_address()
    if not SSH_CONF_DIR.is_dir():
        SSH_CONF_DIR.mkdir()
    if not UNSECURE_PRIV_KEY_FILE.exists():
        UNSECURE_PRIV_KEY_FILE.write_bytes(UNSECURE_ECDSA_KEYPAIR["openssh-priv"])
        UNSECURE_PRIV_KEY_FILE.chmod(0o600)
    if not UNSECURE_PUB_KEY_FILE.exists():
        UNSECURE_PUB_KEY_FILE.write_bytes(UNSECURE_ECDSA_KEYPAIR["openssh-pub"])
    while True:
        try:
            cred_info = check_output(
                ssh_with_identity(
                    str(UNSECURE_PRIV_KEY_FILE),
                    SSH_AUTH_COMMAND.strip()
                    % dict(
                        connect_timeout=SSH_CONNECT_TIMEOUT,
                        unsecure_priv_key=str(UNSECURE_PRIV_KEY_FILE),
                        walt_vpn_entrypoint=walt_vpn_entrypoint,
                        mac_address=mac_address,
                    ),
                ),
                timeout=AUTH_TIMEOUT,
            ).decode("ascii")
        except TimeoutExpired:
            print("Connection timed out.")
            continue
        parts = cred_info.split("\n\n")
        if len(parts) < 2 or parts[0] not in ("FAILED", "OK"):
            print("Wrong server response. Will retry shortly.")
            sleep(5)
            continue
        if parts[0] == "FAILED":
            print("Issue: %s\nWill retry in a moment." % parts[1].strip())
            sleep(15)
            continue
        # OK
        PRIV_KEY_FILE.write_text(parts[1].strip() + "\n")
        PRIV_KEY_FILE.chmod(0o600)
        CERT_PUB_KEY_FILE.write_text(parts[2].strip() + "\n")
        print("OK, new credentials obtained and saved.")
        break


def do_vpn_client(info, walt_vpn_entrypoint):
    # setup credentials if needed
    if not PRIV_KEY_FILE.exists():
        sys.exit(
            "Run the following command once, first:"
            " 'walt-vpn-setup-credentials <walt-server>'"
        )

    # Create TAP
    tap, tap_name = createtap()

    # create bridge
    if not (Path("/sys/class/net") / BRIDGE_INTF).exists():
        check_call("ip link add %s type bridge" % BRIDGE_INTF, shell=True)
    check_call("ip link set up dev %s" % BRIDGE_INTF, shell=True)

    # bring it up, add it to bridge
    check_call("ip link set up dev %(intf)s" % dict(intf=tap_name), shell=True)
    check_call("ip link set master " + BRIDGE_INTF + " dev " + tap_name, shell=True)

    print("added " + tap_name + " to bridge " + BRIDGE_INTF)

    # start loop
    if DEBUG or info.foreground:
        print("Running...")
        Path(PID_FILE).write_text("%d\n" % os.getpid())
        vpn_client_loop(tap, walt_vpn_entrypoint)
    else:
        print("Going to background.")
        with daemon.DaemonContext(files_preserve=[tap], pidfile=PIDLockFile(PID_FILE)):
            vpn_client_loop(tap, walt_vpn_entrypoint)


def vpn_client_loop(tap, walt_vpn_entrypoint):
    while True:
        # Start the command to connect to server
        popen = Popen(
            ssh_with_identity(
                str(PRIV_KEY_FILE),
                SSH_VPN_COMMAND.strip()
                % dict(
                    connect_timeout=SSH_CONNECT_TIMEOUT,
                    priv_key=str(PRIV_KEY_FILE),
                    walt_vpn_entrypoint=walt_vpn_entrypoint,
                ),
            ),
            stdin=PIPE,
            stdout=PIPE,
            bufsize=0,
        )
        # transmit packets
        should_continue = client_transmission_loop(
            popen.stdin.fileno(), popen.stdout.fileno(), tap.fileno()
        )
        print("Transfer loop ended.")
        if not should_continue:
            break
        sleep(5)
        print("Restarting.")


class WalTVPNClient(LoggedApplication):
    """Establish the VPN up to walt server"""

    foreground = cli.Flag(["f", "foreground"], help="Run in foreground")

    def main(self, walt_vpn_entrypoint):
        self.init_logs()
        do_vpn_client(self, walt_vpn_entrypoint)


def vpn_client():
    WalTVPNClient.run()


class WalTVPNSetupCredentials(LoggedApplication):
    """Establish VPN credentials with walt server"""

    def main(self, walt_vpn_entrypoint):
        self.init_logs()
        vpn_setup_credentials(walt_vpn_entrypoint)


def setup_credentials():
    WalTVPNSetupCredentials.run()
