#!/usr/bin/env python
from socket import (
    IPPROTO_TCP,
    SO_KEEPALIVE,
    SOL_SOCKET,
    TCP_KEEPCNT,
    TCP_KEEPIDLE,
    TCP_KEEPINTVL,
)

from walt.common.tcp import Requests

# Send a keepalive probe every TCP_KEEPALIVE_IDLE_TIMEOUT seconds
# unless one of them gets no response.
# In this case send up to TCP_KEEPALIVE_FAILED_COUNT probes
# with an interval of TCP_KEEPALIVE_PROBE_INTERVAL, and if all
# probes fail consider the connection is lost.

TCP_KEEPALIVE_IDLE_TIMEOUT = 15
TCP_KEEPALIVE_PROBE_INTERVAL = 2
TCP_KEEPALIVE_FAILED_COUNT = 5


class NodeBootupStatusListener:
    REQ_ID = Requests.REQ_NOTIFY_BOOTUP_STATUS

    def __init__(self, sock_file, nodes_manager, sock_files_per_ip, **kwargs):
        self.sock_file = sock_file
        self.sock_files_per_ip = sock_files_per_ip
        self.nodes_manager = nodes_manager
        self.node_ip, _ = self.sock_file.getpeername()
        self.sock_files_per_ip[self.node_ip] = self.sock_file
        self.sock_file.write(b'OK\n')
        self._confirmed = False

    def set_keepalive(self):
        self.sock_file.setsockopt(SOL_SOCKET, SO_KEEPALIVE, 1)
        self.sock_file.setsockopt(IPPROTO_TCP, TCP_KEEPIDLE, TCP_KEEPALIVE_IDLE_TIMEOUT)
        self.sock_file.setsockopt(
            IPPROTO_TCP, TCP_KEEPINTVL, TCP_KEEPALIVE_PROBE_INTERVAL
        )
        self.sock_file.setsockopt(IPPROTO_TCP, TCP_KEEPCNT, TCP_KEEPALIVE_FAILED_COUNT)

    # let the event loop know what we are reading on
    def fileno(self):
        if self.sock_file.closed:
            return None
        return self.sock_file.fileno()

    def confirm_bootup(self):
        self._confirmed = True
        self.set_keepalive()
        self.nodes_manager.change_nodes_bootup_status(
            nodes_ip=[self.node_ip], booted=True
        )

    # handle_event() will be called when the event loop detects
    # something for us
    def handle_event(self, ts):
        try:
            c = self.sock_file.read(1)
            if len(c) == 1:
                # all is fine
                if not self._confirmed:
                    self.confirm_bootup()
                return True  # continue
            else:
                err = "empty read"
        except Exception as e:
            err = str(e)
        # If we are here, there was an Exception or an empty read, which means
        # the connection was lost.
        # however, detecting a lost connection might take time and actually
        # happen after the node has rebooted and established a new connection.
        # thus we verify that we are managing the latest connection of this node.
        if (
                self._confirmed and
                self.sock_files_per_ip.get(self.node_ip) is self.sock_file
           ):
            print(f"bootup status listener of {self.node_ip}:", err)
            self.nodes_manager.change_nodes_bootup_status(
                nodes_ip=[self.node_ip], booted=False
            )
        return False  # we should be removed from the event loop

    def close(self):
        if self.sock_file:
            if self.sock_files_per_ip[self.node_ip] is self.sock_file:
                del self.sock_files_per_ip[self.node_ip]
            self.sock_file.close()
            self.sock_file = None


class NodeBootupStatusManager(object):
    def __init__(self, tcp_server, nodes_manager):
        self.sock_files_per_ip = {}
        for cls in [NodeBootupStatusListener]:
            tcp_server.register_listener_class(
                req_id=cls.REQ_ID,
                cls=cls,
                nodes_manager=nodes_manager,
                sock_files_per_ip=self.sock_files_per_ip,
            )
