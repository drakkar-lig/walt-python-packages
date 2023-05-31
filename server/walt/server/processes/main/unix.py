#!/usr/bin/env python
import os.path
import pickle

from walt.common.unix import Requests, UnixServer, send_msg_fds
from walt.server.const import UNIX_SERVER_SOCK_PATH

NODE_TFTP_ROOT = "/var/lib/walt/nodes/%(node_id)s/tftp"


class FakeTFTPGetFDListener:
    REQ_ID = Requests.REQ_FAKE_TFTP_GET_FD

    def send_ok_plus_fd(self, s, peer_addr, fd):
        msg = {"status": "OK"}
        send_msg_fds(s, pickle.dumps(msg), (fd,), peer_addr)

    def send_error(self, s, peer_addr, error_msg):
        msg = {"status": "KO", "error_msg": error_msg}
        send_msg_fds(s, pickle.dumps(msg), (), peer_addr)

    def run(self, s, peer_addr, node_mac=None, node_ip=None, **params):
        if node_mac is not None:
            params["node_id"] = node_mac
        elif node_ip is not None:
            params["node_id"] = node_ip
        else:
            self.send_error(s, peer_addr, "NO MAC OR IP SPECIFIED")
            return
        full_path = (NODE_TFTP_ROOT + "%(path)s") % params
        if not os.path.exists(full_path):
            self.send_error(s, peer_addr, "NO SUCH FILE")
            return
        # all is fine, open the file and send the file descriptor
        # as ancilliary socket data
        with open(full_path, "rb", buffering=0) as f:
            try:
                self.send_ok_plus_fd(s, peer_addr, f.fileno())
            except Exception:
                print("Failed to send reply to walt-server-httpd (probably down)")


class UnixSocketServer(UnixServer):
    def __init__(self):
        UnixServer.__init__(self, UNIX_SERVER_SOCK_PATH)
        for cls in [FakeTFTPGetFDListener]:
            self.register_listener_class(req_id=cls.REQ_ID, cls=cls)
