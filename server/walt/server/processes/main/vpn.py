import os
import pickle
import shlex
import signal
import sys
import tempfile

from pathlib import Path
from subprocess import run
from walt.common.tools import do
from walt.server import conf
from walt.server.vpn.const import (
        VPN_CA_KEY,
        VPN_SERVER_KRL,
        VPN_HTTP_EP_HISTORY_FILE,
)
from walt.server.tools import get_walt_subnet

ERR_VPN_EP_NOT_CONFIGURED = (
"The VPN entrypoint is not fully configured "
"(use 'walt-server-setup --edit-conf' on server-side).")
ROUTE_LOCALNET_SETTING = Path("/proc/sys/net/ipv4/conf/walt-net/route_localnet")
WALT_SUBNET = str(get_walt_subnet())

# Notes:
# * The raspberry pi 5 works as a WALT VPN node by using HTTP
#   for the early boot steps and then an ssh tunnel.
# * The board has no TPM, so the VPN secrets are stored in the
#   eeprom, and anyone able to open a shell on the node is able
#   to read them. We consider that people having access to
#   the walt platform are legitimate users, and we just protect
#   these secrets from other people. The raspberry pi is
#   configured to boot only boot files signed by the walt server,
#   including an intramfs which will connect the SSH tunnel
#   and boot the remote walt image over the tunnel. The default
#   image for rpi5 boards has no root password, so only walt users
#   are able to log in and read the VPN secrets.
# * The server is configured with itself as HTTP and SSH
#   entrypoints by default (unless its FQDN appears invalid).
# * Provided this server configuration is valid, rpi5 VPN nodes
#   are automatically enrolled as VPN nodes on the first boot.
# * As a VPN node, they can boot from another network as long as
#   the VPN endpoints are reachable.
# * But VPN nodes can still be booted from the walt network too.
#   VPN Nodes detect that they are on the walt network when the
#   domain name is "walt". In this case, an SSH connection is still
#   attempted to "walt-vpn@server.walt" for verifying that the server
#   is legitimate. This prevents any attempt to boot the node on
#   a specially crafted network named "walt".
# * The early rpi5 boot up phase is using the HTTP boot feature of
#   the board firmware, once the VPN mode is enabled. It downloads
#   a FAT image and a signature file from the VPN HTTP entrypoint,
#   which redirects to the walt server.
# * In case the VPN-enabled rpi5 is booting from the walt network,
#   the VPN HTTP entrypoint may not be reachable (unless the node is
#   configured with netsetup=NAT). For this reason, the walt server
#   defines DNAT rules to catch this HTTP traffic and handle it
#   locally (see the definition of firewall rules in the code below).
# * If the HTTP entrypoint is reconfigured on server side, one can
#   still make the rpi5 boards boot and auto-update their eeprom
#   with the new value, by just connecting them to the walt network.
#   This works even if the previous HTTP entrypoint is no longer
#   reachable, because the DNAT rules match all VPN HTTP entrypoints
#   ever configured on the platform. (However, this previous HTTP
#   entrypoint must still exist in the DNS.)


class VPNManager:
    def __init__(self, server):
        self.server = server
        self.http_ep_history = self.load_http_ep_history()

    def get_vpn_entrypoint(self, proto):
        entrypoint = None
        vpn_conf = conf.get("vpn")
        if vpn_conf is not None:
            entrypoint = vpn_conf.get(f"{proto}-entrypoint")
        if proto == "http" and entrypoint is not None:
            ep = (entrypoint, 80)
            if ep not in self.http_ep_history:
                self.http_ep_history.add(ep)
                self.save_http_ep_history()
                self.update_vpn_dnat()
        return entrypoint

    def get_vpn_boot_mode(self):
        vpn_conf = conf.get("vpn")
        if vpn_conf is None:
            return None
        return vpn_conf.get("boot-mode")

    def prepare(self):
        ROUTE_LOCALNET_SETTING.write_text("1\n")
        do("iptables -t nat --new-chain WALT-DNAT")
        do("iptables -t nat --append PREROUTING "
           f"--source {WALT_SUBNET} "
         f"! --destination {WALT_SUBNET} "
            "--jump WALT-DNAT")
        self.update_vpn_dnat()

    def update_vpn_dnat(self):
        do("iptables -t nat --flush WALT-DNAT")
        for ep_host, ep_port in self.http_ep_history:
            do("iptables -t nat --append WALT-DNAT "
              f"-p tcp -d {ep_host} --dport {ep_port} "
               "-j DNAT --to-destination 127.0.0.1")
        do("iptables -t nat --append WALT-DNAT --jump RETURN")

    def cleanup(self):
        ROUTE_LOCALNET_SETTING.write_text("0\n")
        do("iptables -t nat --delete PREROUTING "
           f"--source {WALT_SUBNET} "
         f"! --destination {WALT_SUBNET} "
            "--jump WALT-DNAT")
        do("iptables -t nat --flush WALT-DNAT")
        do("iptables -t nat --delete-chain WALT-DNAT")

    def load_http_ep_history(self):
        if VPN_HTTP_EP_HISTORY_FILE.exists():
            return pickle.loads(VPN_HTTP_EP_HISTORY_FILE.read_bytes())
        else:
            return set()

    def save_http_ep_history(self):
        pickled = pickle.dumps(self.http_ep_history)
        VPN_HTTP_EP_HISTORY_FILE.write_bytes(pickled)

    def get_vpn_node_info(self, ip):
        db_rows = self.server.db.execute(
                """SELECT d.mac, vn.vpnmac, va.pubkeycert
                   FROM devices d, nodes n
                   LEFT JOIN vpnnodes vn on vn.mac = n.mac
                   LEFT JOIN vpnauth va on va.vpnmac = vn.vpnmac
                   WHERE n.mac = d.mac
                     AND n.model = 'rpi-5-b'
                     AND d.ip = %s""", (ip,))
        if len(db_rows) == 0:
            return None
        else:
            return db_rows[0]

    def enrollment(self, ip, pubkey):
        vpn_node = self.get_vpn_node_info(ip)
        # if API request is not from a rpi5 node, error out
        if vpn_node is None:
            error_msg = ("VPN enrollment request not coming from "
                         "a rpi5 node of the WalT network.")
            return {"status": "KO", "error_msg": error_msg}
        # if the VPN entrypoint is not fully configured, error out
        if (self.get_vpn_entrypoint("ssh") is None or
            self.get_vpn_entrypoint("http") is None):
            return {"status": "KO", "error_msg": ERR_VPN_EP_NOT_CONFIGURED}
        # OK let's continue
        # Let's sign the pubkey
        device_mac = vpn_node.mac
        cert_id = "vpn_" + device_mac.replace(":", "")
        with tempfile.TemporaryDirectory() as tmpdirname:
            tmpdir = Path(tmpdirname)
            pubkey_path = tmpdir / "key.pub"
            pubkey_path.write_bytes(pubkey)
            do(f"ssh-keygen -s {VPN_CA_KEY} -I '{cert_id}' "
               f"-n 'walt-vpn' {pubkey_path}")
            pubkeycert_path = (tmpdir / "key-cert.pub")
            if not pubkeycert_path.exists():
                error_msg = "Failed to sign the public key (probably wrong format)."
                return {"status": "KO", "error_msg": error_msg}
            pubkeycert = pubkeycert_path.read_text()
        if vpn_node.vpnmac is None:
            # generate a mac for the VPN node
            vpnmac = self.server.nodes.generate_free_mac("52:54:00")
            # insert in database
            self.server.db.execute(
                    """INSERT INTO vpnauth(vpnmac, pubkeycert, certid)
                       VALUES (%s, %s, %s)""", (vpnmac, pubkeycert, cert_id))
            self.server.db.execute(
                    """INSERT INTO vpnnodes(mac, vpnmac)
                       VALUES (%s, %s)""", (device_mac, vpnmac))
            # update dhcpd to recognize the vpn mac
            self.server.dhcpd.update()
        else:
            # the node was already enrolled, but it has sent a new
            # enrollment request; its eeprom was probably reset.
            # just update the pubkeycert in database.
            self.server.db.execute(
                    """UPDATE vpnauth
                       SET pubkeycert = %s
                       WHERE vpnmac = %s""", (pubkeycert, vpn_node.vpnmac))
        self.server.db.commit()
        # let the caller know everything went well
        return {"status": "OK"}

    def get_vpn_node_property(self, node_ip, prop_name):
        vpn_node = self.get_vpn_node_info(node_ip)
        # if API request is not from a rpi5 node, error out
        if vpn_node is None:
            return {"status": "KO", "error_msg": "Invalid request."}
        # if the node is not enrolled yet, return an empty property value
        if vpn_node.vpnmac is None:
            return {"status": "OK", "response_text": ""}
        value = getattr(vpn_node, prop_name)
        return {"status": "OK", "response_text": value}

    def dump_ssh_pubkey_cert(self, node_ip):
        return self.get_vpn_node_property(node_ip, "pubkeycert")

    def get_vpn_mac(self, node_ip):
        return self.get_vpn_node_property(node_ip, "vpnmac")

    def generate_ssh_ep_host_keys(self):
        ssh_entrypoint = self.get_vpn_entrypoint("ssh")
        if ssh_entrypoint is None:
            return {"status": "KO", "error_msg": ERR_VPN_EP_NOT_CONFIGURED}
        host_keys = run(shlex.split(f"ssh-keyscan -H {ssh_entrypoint}"),
                        capture_output=True,
                        text=True).stdout
        return {"status": "OK", "response_text": host_keys}

    def get_mac_from_vpn_mac(self, vpnmac):
        db_row = self.server.db.select_unique("vpnnodes", vpnmac=vpnmac)
        if db_row is None:
            return None
        else:
            return db_row.mac

    def revoke_vpn_auth_key(self, cert_id):
        vpn_auth = self.server.db.select_unique("vpnauth", certid=cert_id)
        if vpn_auth is None:
            return {"status": "KO", "error_msg": "Did not find such VPN key."}
        if vpn_auth.revoked:
            return {"status": "KO", "error_msg": "This VPN key was already revoked."}
        # update db
        self.server.db.revoke_vpn_auth_key(vpn_auth.vpnmac)
        # add cert ID to the Key Revocation List
        run(shlex.split(
            f"ssh-keygen -k -u -s {VPN_CA_KEY} -f {VPN_SERVER_KRL} -"),
            input=f"id: {cert_id}",
            text=True)
        # reload sshd
        pid = int(Path("/run/sshd.pid").read_text())
        os.kill(pid, signal.SIGHUP)
