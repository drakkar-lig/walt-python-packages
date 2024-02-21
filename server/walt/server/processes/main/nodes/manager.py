import base64
import random

from time import time

from walt.server.const import SSH_COMMAND
from walt.server.popen import BetterPopen
from walt.server.processes.main.filesystem import FilesystemsCache
from walt.server.processes.main.nodes.clock import NodesClockSyncInfo
from walt.server.processes.main.nodes.expose import ExposeManager
from walt.server.processes.main.nodes.netservice import node_request
from walt.server.processes.main.nodes.powersave import PowersaveManager
from walt.server.processes.main.nodes.reboot import reboot_nodes
from walt.server.processes.main.nodes.register import handle_registration_request
from walt.server.processes.main.nodes.show import show
from walt.server.processes.main.nodes.status import NodeBootupStatusManager
from walt.server.processes.main.nodes.wait import WaitInfo
from walt.server.processes.main.workflow import Workflow
from walt.server.tools import get_server_ip, get_walt_subnet, ip

VNODE_DEFAULT_RAM = "512M"
VNODE_DEFAULT_CPU_CORES = 4
VNODE_DEFAULT_DISKS = "none"
VNODE_DEFAULT_NETWORKS = "walt-net"
VNODE_DEFAULT_BOOT_DELAY = "random"
NODE_DEFAULT_BOOT_RETRIES = 9
NODE_DEFAULT_BOOT_TIMEOUT = 180
NODE_MIN_BOOT_TIMEOUT = 60

MSG_NOT_VIRTUAL = "WARNING: %s is not a virtual node. IGNORED.\n"

FS_CMD_PATTERN = SSH_COMMAND + ' root@%(fs_id)s "sh"'  # use node_ip as our fs ID

CMD_START_VNODE = (
    "walt-virtual-node --hostname %(name)s --mac %(mac)s --ip %(ip)s --model %(model)s"
    "                  --server-ip %(server_ip)s --cpu-cores %(cpu_cores)d"
    "                  --ram %(ram)s --disks %(disks)s --networks %(networks)s"
    "                  --boot-delay %(boot_delay)s --managed"
)


class NodesManager(object):
    def __init__(self, server):
        self.db = server.db
        self.devices = server.devices
        self.logs = server.logs
        self.blocking = server.blocking
        self.wait_info = WaitInfo()
        self.ev_loop = server.ev_loop
        self.exports = server.exports
        self.clock = NodesClockSyncInfo(server.ev_loop)
        self.expose_manager = ExposeManager(server.tcp_server, server.ev_loop)
        self.status_manager = NodeBootupStatusManager(server.tcp_server, self)
        self.filesystems = FilesystemsCache(server.ev_loop, FS_CMD_PATTERN)
        self.vnodes = {}
        self.booted_macs = set()
        self.powersave = PowersaveManager(server)
        self.node_register_kwargs = dict(
            images=server.images.store, dhcpd=server.dhcpd,
            named=server.named, registry=server.registry
        )
        self.pending_boot_info = {}
        self.next_boot_check = None

    def is_booted_node_mac(self, mac):
        return mac in self.booted_macs

    def forget_device(self, mac):
        self.booted_macs.discard(mac)  # if ever it was inside
        if mac in self.pending_boot_info:
            del self.pending_boot_info[mac]

    def prepare(self):
        pass

    def restore(self):
        # init powersave
        self.powersave.restore()
        # initialize pending_boot_info
        now = time()
        for node in self.db.select("devices", type="node"):
            boot_timeout = node.conf.get("boot.timeout", NODE_DEFAULT_BOOT_TIMEOUT)
            boot_retries = node.conf.get("boot.retries", NODE_DEFAULT_BOOT_RETRIES)
            self.pending_boot_info[node.mac] = dict(
                    timeout=boot_timeout,
                    retries=boot_retries,
                    remaining_retries=boot_retries,
                    cause="startup",
                    boot_start_time=now
            )
        self._plan_pending_boot_check()
        # start virtual nodes
        for vnode in self.db.select("devices", type="node", virtual=True):
            node = self.devices.get_complete_device_info(vnode.mac)
            self.start_vnode(node)

    def update_node_boot_retries(self, node_mac, retries):
        old_retries = self.pending_boot_info[node_mac]["retries"]
        old_remaining_retries = self.pending_boot_info[node_mac]["remaining_retries"]
        remaining_retries = old_remaining_retries + retries - old_retries
        if remaining_retries < 0:
            remaining_retries = 0
        self.pending_boot_info[node_mac].update(
                retries=retries,
                remaining_retries=remaining_retries
        )
        self._plan_pending_boot_check()

    def update_node_boot_timeout(self, node_mac, timeout):
        self.pending_boot_info[node_mac].update(timeout=timeout)
        self._plan_pending_boot_check()

    def record_nodes_boot_start(self, nodes):
        now = time()
        for node in nodes:
            if node.mac not in self.booted_macs:
                self.pending_boot_info[node.mac].update(boot_start_time=now)
        self._plan_pending_boot_check()

    def _get_node_boot_timeout(self, mac):
        if mac in self.booted_macs:
            return None
        info = self.pending_boot_info[mac]
        if info["timeout"] is None:
            return None
        if info["remaining_retries"] == 0:
            return None
        if info.get("cause") == "powersave":
            return None
        return info["boot_start_time"] + info["timeout"]

    def _plan_pending_boot_check(self):
        next_boot_check = self.next_boot_check
        for mac in self.pending_boot_info.keys():
            node_boot_check = self._get_node_boot_timeout(mac)
            if node_boot_check is None:
                continue
            if next_boot_check is None:
                next_boot_check = node_boot_check
            else:
                next_boot_check = min(node_boot_check, next_boot_check)
        if next_boot_check is None:
            return  # nothing to monitor
        if self.next_boot_check is None or self.next_boot_check > next_boot_check:
            self.next_boot_check = next_boot_check
            self.ev_loop.plan_event(ts=next_boot_check, callback=self._boot_check)

    def _boot_check(self):
        self.next_boot_check = None
        now = time()
        failing_nodes = []
        for mac, info in self.pending_boot_info.items():
            node_boot_timeout = self._get_node_boot_timeout(mac)
            if node_boot_timeout is None:
                continue
            if now >= node_boot_timeout:
                node = self.devices.get_complete_device_info(mac)
                info["remaining_retries"] -= 1
                remaining_retries = info["remaining_retries"]
                logline = f"{node.name}: boot timeout reached, trying hard-reboot "
                if remaining_retries > 0:
                    logline += f"({remaining_retries} retries left)."
                else:
                    logline += "(last try)."
                self.logs.platform_log("nodes", logline)
                failing_nodes.append(node)
                # We will hard reboot this node below, but if hard-reboot fails,
                # boot start time will not be updated. So we artificially set it
                # now to force a delay of NODE_DEFAULT_BOOT_TIMEOUT before the next
                # hard-reboot try, in this failure case.
                info["boot_start_time"] = now
        # reboot nodes if needed and then plan next check
        if len(failing_nodes) > 0:
            def cb(status):
                self._plan_pending_boot_check()
            self.reboot_nodes(None, cb, failing_nodes, True, "bootup timeout",
                              reset_boot_retries=False)
        else:
            self._plan_pending_boot_check()

    def try_kill_vnode(self, node_mac):
        if node_mac in self.vnodes:
            popen, listener = self.vnodes[node_mac]
            listener.close()
            popen.close()
            del self.vnodes[node_mac]

    def cleanup(self):
        # stop virtual nodes
        for vnode in self.db.select("devices", type="node", virtual=True):
            print(f"stop vnode {vnode.name}")
            self.try_kill_vnode(vnode.mac)
        # cleanup filesystem interpreters
        self.filesystems.cleanup()

    def forget_vnode(self, node_mac):
        self.try_kill_vnode(node_mac)
        # note: the calling code takes care of discarding db data
        # about this vnode (see server.py)

    def register_node(self, mac, model, image_fullname=None):
        self.pending_boot_info[mac] = dict(
            timeout=NODE_DEFAULT_BOOT_TIMEOUT,
            retries=NODE_DEFAULT_BOOT_RETRIES,
            remaining_retries=NODE_DEFAULT_BOOT_RETRIES,
            cause="startup",
            boot_start_time=time()
        )
        self._plan_pending_boot_check()
        handle_registration_request(
            db=self.db,
            devices=self.devices,
            mac=mac,
            model=model,
            image_fullname=image_fullname,
            blocking=self.blocking,
            logs=self.logs,
            exports=self.exports,
            **self.node_register_kwargs,
        )

    def blink_callback(self, results, requester, task):
        # we have just one node, so one entry in results
        result_msg = tuple(results.keys())[0]
        node = results[result_msg][0]
        if result_msg == "OK":
            task.return_result(True)
        else:
            requester.stderr.write(
                "Blink request to %s failed: %s\n" % (node.name, result_msg)
            )
            task.return_result(False)

    def blink(self, requester, task, node_name, blink_status):
        req = "BLINK %d" % int(blink_status)
        node = self.get_node_info(requester, node_name)
        if node is None:
            return False  # error already reported
        task.set_async()
        cb_kwargs = dict(requester=requester, task=task)
        node_request(self.ev_loop, (node,), req, self.blink_callback, cb_kwargs)

    def show(self, username, show_all, names_only):
        return show(self, username, show_all, names_only)

    def generate_vnode_info(self):
        # random mac address generation
        while True:
            free_mac = "52:54:00:%02x:%02x:%02x" % (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255),
            )
            if self.db.select_unique("devices", mac=free_mac) is None:
                break  # ok, mac is free
        # find a free ip
        subnet = get_walt_subnet()
        server_ip = get_server_ip()
        free_ips = set(subnet.hosts())
        free_ips.discard(ip(server_ip))
        for item in self.db.execute("SELECT ip FROM devices WHERE ip IS NOT NULL"):
            device_ip = ip(item.ip)
            if device_ip in subnet and device_ip in free_ips:
                free_ips.discard(device_ip)
        free_ip = str(min(free_ips))
        return free_mac, free_ip, "pc-x86-64"

    def start_vnode(self, node):
        # start vnode
        cmd = CMD_START_VNODE % dict(
            mac=node.mac,
            ip=node.ip,
            model=node.model,
            name=node.name,
            server_ip=get_server_ip(),
            cpu_cores=node.conf.get("cpu.cores", VNODE_DEFAULT_CPU_CORES),
            ram=node.conf.get("ram", VNODE_DEFAULT_RAM),
            disks=node.conf.get("disks", VNODE_DEFAULT_DISKS),
            networks=node.conf.get("networks", VNODE_DEFAULT_NETWORKS),
            boot_delay=node.conf.get("boot.delay", VNODE_DEFAULT_BOOT_DELAY),
        )
        print(cmd)
        popen = BetterPopen(
            self.ev_loop,
            cmd,
            lambda popen: popen.stdin.write(b'EXIT\n'),
            shell=False,
        )
        listener = self.logs.monitor_file(popen.stdout, node.ip, "virtualconsole")
        self.vnodes[node.mac] = popen, listener

    def vnode_hard_reboot(self, node_mac):
        popen = self.vnodes[node_mac][0]
        popen.stdin.write(b'KILL_VM\n')

    def vnode_console_input(self, node_mac, buf):
        # qemu has escape sequences starting with <ctrl-a>. we do not want
        # to let them accessible to the user.
        # to send a <ctrl-a> to the guest, we send <ctrl-a><ctrl-a> to qemu.
        if buf == b"\x01":
            buf = b"\x01\x01"
        popen = self.vnodes[node_mac][0]
        popen.stdin.write(b'INPUT ' + base64.b64encode(buf) + b'\n')

    def vnode_update_vm_setting(self, node_mac, setting_name, setting_value):
        popen = self.vnodes[node_mac][0]
        popen.stdin.write(f"CONF {setting_name} {setting_value}\n".encode("ascii"))

    def get_node_info(self, requester, node_name):
        device_info = self.devices.get_device_info(requester, node_name)
        if device_info is None:
            return None  # error already reported
        device_type = device_info.type
        if device_type != "node":
            # if the user uses "walt device forget" but the node is still
            # there, it may be detected by the DHCP server and temporarily
            # recorded again as an unknown device. When the previous bootup
            # monitoring connection ends at this time, this function gets
            # called with requester set to None and we get here.
            if requester is not None:
                requester.stderr.write(
                    "%s is not a node, it is a %s.\n" % (node_name, device_type)
                )
            return None
        return self.devices.get_complete_device_info(device_info.mac)

    def get_virtual_node_info(self, requester, node_name):
        node = self.get_node_info(requester, node_name)
        if node is None:
            return None  # error already reported
        if not node.virtual:
            requester.stderr.write(
                "FAILED: %s is a real node (not virtual).\n" % node_name
            )
            return None
        return node

    def get_node_ip(self, requester, node_name):
        node_info = self.get_node_info(requester, node_name)
        if node_info is None:
            return None  # error already reported
        if node_info.ip is None:
            self.notify_unknown_ip(requester, node_name)
        return node_info.ip

    def get_nodes_ip(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes is None:
            return ()  # error already reported
        return tuple(node.ip for node in nodes)

    def get_nodes_info(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes is None:
            return ()  # error already reported
        return nodes

    def get_nodes_using_image(self, image_fullname):
        nodes = self.db.select("nodes", image=image_fullname)
        return tuple(self.devices.get_complete_device_info(n.mac) for n in nodes)

    def get_node_models_using_image(self, image_fullname):
        return set(node.model for node in self.db.select("nodes", image=image_fullname))

    def reboot_node_set(self, requester, task, node_set, hard_only, reboot_cause):
        nodes = self.parse_node_set(requester, node_set)
        if nodes is None:
            return None  # error already reported
        task.set_async()
        self.reboot_nodes(requester, task.return_result, nodes, hard_only, reboot_cause)

    def reboot_nodes(self, requester, task_callback, nodes, hard_only, reboot_cause,
                     reset_boot_retries=True):
        if reset_boot_retries:
            for node in nodes:
                retries = self.pending_boot_info[node.mac]["retries"]
                self.pending_boot_info[node.mac].update(remaining_retries=retries)
        reboot_nodes(
            nodes_manager=self,
            blocking=self.blocking,
            ev_loop=self.ev_loop,
            db=self.db,
            powersave=self.powersave,
            requester=requester,
            task_callback=task_callback,
            nodes=nodes,
            hard_only=hard_only,
            reboot_cause=reboot_cause,
        )

    def parse_node_set(self, requester, node_set):
        device_set = self.devices.parse_device_set(requester, node_set)
        if device_set is None:
            return None
        for device_info in device_set:
            if device_info.type != "node":
                requester.stderr.write(
                    "%s is not a node, it is a %s.\n"
                    % (device_info.name, device_info.type)
                )
                return None
        return device_set

    def change_nodes_bootup_status(
        self, nodes_ip=None, nodes=None, booted=True, **details
    ):
        if nodes is None:
            nodes = []
        if nodes_ip is not None:
            for node_ip in nodes_ip:
                node_info = None
                node_name = self.devices.get_name_from_ip(node_ip)
                if node_name is not None:
                    node_info = self.get_node_info(None, node_name)
                if node_info is None:
                    # if a virtual node was removed or a node was forgotten,
                    # when tcp connection timeout is reached we get here. ignore.
                    continue
                nodes.append(node_info)
        now = time()
        for node_info in nodes:
            mac = node_info.mac
            # note: change_nodes_bootup_status() may be called as a callback
            # of the netservice.py procedure, thus the "nodes" parameter may be
            # outdated regarding the "booted" attribute. So we recompute it.
            old_booted = (mac in self.booted_macs)
            if old_booted != booted:
                # add or remove from self.booted_macs and generate a log line
                if booted:
                    self.booted_macs.add(mac)
                    status = "booted"
                else:
                    self.booted_macs.discard(mac)
                    status = "down"
                    cause = details.get("cause", None)
                    # note: if this node went down unexpectedly, we have no idea
                    # when it started to reboot, so set boot_start_time to now
                    # (i.e., the time when we detect it is down).
                    # if it was expected, then boot_start_time will be updated
                    # again shortly (e.g., in the case of a hard-reboot, when PoE
                    # is re-enabled).
                    self.pending_boot_info[mac].update(
                        remaining_retries=self.pending_boot_info[mac]["retries"],
                        boot_start_time=now,
                        cause=cause
                    )
                logline = f"node {node_info.name} is {status}"
                if len(details) > 0:
                    s_details = ", ".join(
                        f"{k}: {v}" for k, v, in details.items())
                    logline += f" ({s_details})"
                self.logs.platform_log("nodes", logline)
                node_info.booted = booted
                # unblock any related "walt node wait" command.
                if booted:
                    self.wait_info.node_bootup_event(node_info)
                    self.powersave.node_bootup_event(node_info)
        self._plan_pending_boot_check()

    def develop_node_set(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes is None:
            return None
        return self.devices.as_device_set(n.name for n in nodes)

    def validate_cp_entity(self, requester, node_name, index, **info):
        if self.get_node_info(requester, node_name) is None:
            return "FAILED"
        else:
            return "OK"

    def get_node_filesystem(self, requester, node_name):
        node_ip = self.get_node_ip(requester, node_name)
        if node_ip is None:
            return None
        self.devices.prepare_ssh_access_for_ip(node_ip)
        return self.filesystems[node_ip]

    def get_cp_entity_filesystem(self, requester, node_name, **info):
        return self.get_node_filesystem(requester, node_name)

    def get_cp_entity_attrs(self, requester, node_name, **info):
        owned, free, not_owned, _ = self.filter_ownership(requester, node_name)
        ownership = "error"
        if len(owned) == 1:
            ownership = "owned"
        elif len(free) == 1:
            ownership = "free"
        elif len(not_owned) == 1:
            ownership = "not_owned"
        node_info = self.get_node_info(requester, node_name)
        return dict(
            node_name=node_info.name,
            node_ip=node_info.ip,
            node_image=node_info.image,
            node_ownership=ownership,
        )

    def filter_ownership(self, requester, node_set):
        username = requester.get_username()
        if not username:
            return (), (), (), ()  # client already disconnected, give up
        devices = self.devices.parse_device_set(requester, node_set)
        if devices is None:
            return (), (), (), ()
        owned, free, not_owned, not_nodes = (), (), (), ()
        for n in devices:
            if n.type != "node":
                not_nodes += (n.name,)
            elif n.image.startswith(username + "/"):
                owned += (n.name,)
            elif n.image.startswith("waltplatform/"):
                free += (n.name,)
            else:
                not_owned += (n.name,)
        return owned, free, not_owned, not_nodes

    def wait(self, requester, task, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes is None:
            return False  # unblock the client
        not_booted = [node for node in nodes if not node.booted]
        if len(not_booted) == 0:
            return True  # unblock the client
        task.set_async()
        wf = Workflow(
            [self.powersave.wf_wakeup_nodes, self.wait_info.wf_wait],
            requester=requester,
            task=task,
            nodes=nodes,
        )
        wf.run()
