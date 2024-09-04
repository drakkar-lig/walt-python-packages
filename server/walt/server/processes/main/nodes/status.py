#!/usr/bin/env python
from socket import (
    IPPROTO_TCP,
    SO_KEEPALIVE,
    SOL_SOCKET,
    TCP_KEEPCNT,
    TCP_KEEPIDLE,
    TCP_KEEPINTVL,
)
from time import time

from walt.common.tcp import Requests

NODE_DEFAULT_BOOT_RETRIES = 9
NODE_DEFAULT_BOOT_TIMEOUT = 180
NODE_MIN_BOOT_TIMEOUT = 60

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

    def __init__(self, manager, sock_file, sock_files_per_ip, **kwargs):
        self.manager = manager
        self.sock_file = sock_file
        self.sock_files_per_ip = sock_files_per_ip
        self.node_ip, _ = self.sock_file.getpeername()
        self.sock_files_per_ip[self.node_ip] = self.sock_file
        self.sock_file.write(b'OK\n')
        self.set_keepalive()
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

    def _add_booted_evt(self, booted):
        self.manager.add_booted_event(self.node_ip, booted, {})

    # handle_event() will be called when the event loop detects
    # something for us
    def handle_event(self, ts):
        try:
            if len(self.sock_file.read(1)) == 1:
                # all is fine
                if not self._confirmed:
                    self._confirmed = True
                    self._add_booted_evt(True)
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
            self._add_booted_evt(False)
        return False  # we should be removed from the event loop

    def close(self):
        if self.sock_file:
            if self.sock_files_per_ip[self.node_ip] is self.sock_file:
                del self.sock_files_per_ip[self.node_ip]
            self.sock_file.close()
            self.sock_file = None


class NodeBootupStatusManager(object):
    def __init__(self, tcp_server, nodes_manager):
        self._sock_files_per_ip = {}
        self._booted_events = []
        self._nodes = nodes_manager
        self._ev_loop = nodes_manager.ev_loop
        self._db = nodes_manager.db
        self._logs = nodes_manager.logs
        self._devices = nodes_manager.devices
        self._booted_macs = set()
        self._pending_boot_info = {}
        self._next_bg_process = None
        self._bg_processing = False
        self._cleaning_up = False
        for cls in [NodeBootupStatusListener]:
            tcp_server.register_listener_class(
                manager=self,
                req_id=cls.REQ_ID,
                cls=cls,
                sock_files_per_ip=self._sock_files_per_ip,
            )

    def cleanup(self):
        self._cleaning_up = True

    def get_booted_macs(self):
        return self._booted_macs.copy()

    def forget_device(self, mac):
        self._booted_macs.discard(mac)  # if ever it was inside
        if mac in self._pending_boot_info:
            del self._pending_boot_info[mac]

    def restore(self):
        # initialize _pending_boot_info
        now = time()
        for node in self._db.select("devices", type="node"):
            boot_timeout = node.conf.get("boot.timeout", NODE_DEFAULT_BOOT_TIMEOUT)
            boot_retries = node.conf.get("boot.retries", NODE_DEFAULT_BOOT_RETRIES)
            self._pending_boot_info[node.mac] = dict(
                    timeout=boot_timeout,
                    retries=boot_retries,
                    remaining_retries=boot_retries,
                    cause="startup",
                    boot_start_time=now
            )
        self._plan_bg_process()

    def add_booted_event(self, *evt):
        self._booted_events.append(evt)
        self._plan_bg_process()

    def update_node_boot_retries(self, node_mac, retries):
        old_retries = self._pending_boot_info[node_mac]["retries"]
        old_remaining_retries = self._pending_boot_info[node_mac]["remaining_retries"]
        remaining_retries = old_remaining_retries + retries - old_retries
        if remaining_retries < 0:
            remaining_retries = 0
        self._pending_boot_info[node_mac].update(
                retries=retries,
                remaining_retries=remaining_retries
        )
        self._plan_bg_process()

    def update_node_boot_timeout(self, node_mac, timeout):
        self._pending_boot_info[node_mac].update(timeout=timeout)
        self._plan_bg_process()

    def record_nodes_boot_start(self, nodes):
        now = time()
        for node in nodes:
            if node.mac not in self._booted_macs:
                self._pending_boot_info[node.mac].update(boot_start_time=now)
        self._plan_bg_process()

    def register_node(self, mac):
        self._pending_boot_info[mac] = dict(
            timeout=NODE_DEFAULT_BOOT_TIMEOUT,
            retries=NODE_DEFAULT_BOOT_RETRIES,
            remaining_retries=NODE_DEFAULT_BOOT_RETRIES,
            cause="startup",
            boot_start_time=time()
        )
        self._plan_bg_process()

    def reset_boot_retries(self, nodes):
        for node in nodes:
            retries = self._pending_boot_info[node.mac]["retries"]
            self._pending_boot_info[node.mac].update(remaining_retries=retries)

    def change_nodes_bootup_status(self, nodes, booted=True, **details):
        for node in nodes:
            self._booted_events.append((node.ip, booted, details))
        self._plan_bg_process()

    def _get_node_boot_timeout(self, mac):
        if mac in self._booted_macs:
            return None
        info = self._pending_boot_info[mac]
        if info["timeout"] is None:
            return None
        if info["remaining_retries"] == 0:
            return None
        if info.get("cause") == "powersave":
            return None
        return info["boot_start_time"] + info["timeout"]

    def _plan_bg_process(self):
        # if bg process is already running, just let it recall
        # _plan_bg_process() when it is done
        if self._bg_processing:
            return
        # otherwise, if some events are pending, call bg process immediately
        if len(self._booted_events) > 0:
            self._bg_process()
            return
        # otherwise, use the event loop to start bg process when the
        # next node should be booted
        next_boot_check = self._next_bg_process
        for mac in set(self._pending_boot_info.keys()) - self._booted_macs:
            node_boot_check = self._get_node_boot_timeout(mac)
            if node_boot_check is None:
                continue
            if next_boot_check is None:
                next_boot_check = node_boot_check
            else:
                next_boot_check = min(node_boot_check, next_boot_check)
        if next_boot_check is None:
            return  # nothing to monitor
        if self._next_bg_process is None or self._next_bg_process > next_boot_check:
            self._next_bg_process = next_boot_check
            self._ev_loop.plan_event(ts=next_boot_check, callback=self._bg_process)

    def _bg_process(self):
        if self._cleaning_up:
            return
        if self._bg_processing:
            return
        self._bg_processing = True
        self._next_bg_process = None
        # process events
        self._bg_process_booted_events()
        # check boot timeouts
        failing_nodes = self._bg_boot_check()
        # reboot nodes if needed and then plan next bg process
        if len(failing_nodes) > 0:
            def cb(status):
                self._bg_processing = False
                self._plan_bg_process()
            self._nodes.reboot_nodes(None, cb, failing_nodes, True, "bootup timeout",
                              reset_boot_retries=False)
        else:
            self._bg_processing = False
            self._plan_bg_process()

    def _bg_process_booted_events(self):
        now = time()
        while len(self._booted_events) > 0:
            ev_info, self._booted_events = (
                    self._booted_events[0], self._booted_events[1:])
            node_ip, booted, details = ev_info
            node_info = None
            node_name = self._devices.get_name_from_ip(node_ip)
            if node_name is not None:
                node_info = self._nodes.get_node_info(None, node_name)
            if node_info is None:
                # if a virtual node was removed or a node was forgotten,
                # when tcp connection timeout is reached we get here. ignore.
                continue
            old_booted = node_info.booted
            if old_booted != booted:
                mac = node_info.mac
                # add or remove from self._booted_macs and generate a log line
                if booted:
                    self._booted_macs.add(mac)
                    status = "booted"
                else:
                    self._booted_macs.discard(mac)
                    status = "down"
                    cause = details.get("cause", None)
                    # note: if this node went down unexpectedly, we have no idea
                    # when it started to reboot, so set boot_start_time to now
                    # (i.e., the time when we detect it is down).
                    # if it was expected, then boot_start_time will be updated
                    # again shortly (e.g., in the case of a hard-reboot, when PoE
                    # is re-enabled).
                    self._pending_boot_info[mac].update(
                        remaining_retries=self._pending_boot_info[mac]["retries"],
                        boot_start_time=now,
                        cause=cause
                    )
                logline = f"node {node_info.name} is {status}"
                if len(details) > 0:
                    s_details = ", ".join(
                        f"{k}: {v}" for k, v, in details.items())
                    logline += f" ({s_details})"
                self._logs.platform_log("nodes", logline)
                # unblock any related "walt node wait" command.
                if booted:
                    self._nodes.wait_info.node_bootup_event(node_info)
                    self._nodes.powersave.node_bootup_event(node_info)
        self._plan_bg_process()

    def _bg_boot_check(self):
        now = time()
        failing_nodes = []
        for mac in set(self._pending_boot_info.keys()) - self._booted_macs:
            node_boot_timeout = self._get_node_boot_timeout(mac)
            if node_boot_timeout is None:
                continue
            if now >= node_boot_timeout:
                info = self._pending_boot_info[mac]
                node = self._devices.get_device_info(mac=mac)
                info["remaining_retries"] -= 1
                remaining_retries = info["remaining_retries"]
                logline = f"{node.name}: boot timeout reached, trying hard-reboot "
                if remaining_retries > 0:
                    logline += f"({remaining_retries} retries left)."
                else:
                    logline += "(last try)."
                self._logs.platform_log("nodes", logline)
                failing_nodes.append(node)
                # We will hard reboot this node below, but if hard-reboot fails,
                # boot start time will not be updated. So we artificially set it
                # now to force a delay of NODE_DEFAULT_BOOT_TIMEOUT before the next
                # hard-reboot try, in this failure case.
                info["boot_start_time"] = now
        return failing_nodes
