#!/usr/bin/env python
import os.path
import sys

from walt.common.tcp import MyPickle as pickle
from walt.common.unix import Requests, UnixServer, send_msg_fds
from walt.server.const import UNIX_SERVER_SOCK_PATH

NODE_TFTP_ROOT = "/var/lib/walt/nodes/%(node_ip)s/tftp"


class BaseUnixSocketListener:

    def send_resp_fd(self, s, peer_addr, resp, fd):
        try:
            if fd is None:
                s.sendto(pickle.dumps(resp), peer_addr)
            else:
                send_msg_fds(s, pickle.dumps(resp), (fd,), peer_addr)
        except Exception:
            print("Failed to send reply to walt-server-httpd (probably down)",
                  file=sys.stderr)

    def send_resp(self, s, peer_addr, resp):
        self.send_resp_fd(s, peer_addr, resp, None)


class VPNEnrollListener(BaseUnixSocketListener):
    REQ_ID = Requests.REQ_VPN_ENROLL

    def __init__(self, server, **params):
        self.server = server

    def run(self, s, peer_addr, node_ip, pubkey, **params):
        result = self.server.vpn.enrollment(ip=node_ip, pubkey=pubkey)
        self.send_resp(s, peer_addr, result)


class FileGeneratorListener(BaseUnixSocketListener):
    REQ_ID = Requests.REQ_GENERATE_FILE

    def __init__(self, server, **params):
        self.server = server

    def run(self, s, peer_addr, file_id, node_ip=None):
        if file_id == "ssh-ep-host-keys":
            result = self.server.vpn.generate_ssh_ep_host_keys()
        elif file_id == "ssh-pubkey-cert":
            result = self.server.vpn.dump_ssh_pubkey_cert(node_ip)
        else:
            result = {"status": "KO", "error_msg": "Invalid file-id."}
        self.send_resp(s, peer_addr, result)


class PropertyListener(BaseUnixSocketListener):
    REQ_ID = Requests.REQ_PROPERTY

    def __init__(self, server, **params):
        self.server = server

    def get_entrypoint_property(self, proto):
        ep = self.server.vpn.get_vpn_entrypoint(proto)
        if ep is None:
            ep = ""
        return {"status": "OK", "response_text": ep}

    def get_vpn_boot_mode(self):
        boot_mode = self.server.vpn.get_vpn_boot_mode()
        if boot_mode is None:
            boot_mode = ""
        return {"status": "OK", "response_text": boot_mode}

    def run(self, s, peer_addr, property_id, node_ip=None):
        if property_id == "node.vpn.mac":
            result = self.server.vpn.get_vpn_mac(node_ip)
        elif property_id == "server.vpn.ssh-entrypoint":
            result = self.get_entrypoint_property("ssh")
        elif property_id == "server.vpn.http-entrypoint":
            result = self.get_entrypoint_property("http")
        elif property_id == "server.vpn.boot-mode":
            result = self.get_vpn_boot_mode()
        else:
            result = {"status": "KO", "error_msg": "Invalid property-id."}
        self.send_resp(s, peer_addr, result)


class FakeTFTPGetFDListener(BaseUnixSocketListener):
    REQ_ID = Requests.REQ_FAKE_TFTP_GET_FD

    def __init__(self, server, **params):
        self.server = server

    def run(self, s, peer_addr, node_ip, path):
        full_path = (NODE_TFTP_ROOT % {"node_ip": node_ip}) + path
        if not os.path.exists(full_path):
            resp = {"status": "KO", "error_msg": "NO SUCH FILE"}
            self.send_resp(s, peer_addr, resp)
            return
        # all is fine, open the file and send the file descriptor
        # as ancilliary socket data
        with open(full_path, "rb", buffering=0) as f:
            self.send_resp_fd(s, peer_addr, {"status": "OK"}, f.fileno())


class UnixSocketServer(UnixServer):
    def __init__(self, server):
        UnixServer.__init__(self, UNIX_SERVER_SOCK_PATH)
        for cls in [FakeTFTPGetFDListener,
                    VPNEnrollListener,
                    FileGeneratorListener,
                    PropertyListener]:
            self.register_listener_class(req_id=cls.REQ_ID, cls=cls, server=server)
