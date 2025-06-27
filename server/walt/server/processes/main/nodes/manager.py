import base64
import random

from pathlib import Path

from walt.server.const import (
        SSH_NODE_COMMAND,
        NODE_SSH_ECDSA_HOST_KEY_PUB_PATH,
)
from walt.server.popen import BetterPopen
from walt.server.processes.main.filesystem import FilesystemsCache
from walt.server.processes.main.nodes.clock import NodesClockSyncInfo
from walt.server.processes.main.nodes.expose import ExposeManager
from walt.server.processes.main.nodes.netservice import node_request
from walt.server.processes.main.nodes.powersave import PowersaveManager
from walt.server.processes.main.nodes.reboot import reboot_nodes
from walt.server.processes.main.nodes.register import handle_registration_request
from walt.server.processes.main.nodes.show import show
from walt.server.processes.main.nodes.webapi import web_api_list_nodes
from walt.server.processes.main.nodes.status import (
        NodeBootupStatusManager,
        NODE_DEFAULT_BOOT_RETRIES,
        NODE_DEFAULT_BOOT_TIMEOUT,
        NODE_MIN_BOOT_TIMEOUT
)
from walt.server.processes.main.nodes.status import NodeBootupStatusManager
from walt.server.processes.main.nodes.wait import WaitInfo
from walt.server.processes.main.workflow import Workflow
from walt.server.tools import get_server_ip, get_walt_subnet, ip

VNODE_DEFAULT_RAM = "512M"
VNODE_DEFAULT_CPU_CORES = 4
VNODE_DEFAULT_DISKS = "none"
VNODE_DEFAULT_NETWORKS = "walt-net"
VNODE_DEFAULT_BOOT_DELAY = "random"

MSG_NOT_VIRTUAL = "WARNING: %s is not a virtual node. IGNORED.\n"

FS_CMD_PATTERN = SSH_NODE_COMMAND + ' root@%(fs_id)s "sh"'  # use node_ip as our fs ID

CMD_START_VNODE = (
    "walt-virtual-node --hostname %(name)s --mac %(mac)s --ip %(ip)s --model %(model)s"
    "                  --server-ip %(server_ip)s --cpu-cores %(cpu_cores)d"
    "                  --ram %(ram)s --disks %(disks)s --networks %(networks)s"
  """                  --netmask %(netmask)s --gateway "%(gateway)s" """
    "                  --boot-delay %(boot_delay)s --managed"
)


class NodesManager(object):
    def __init__(self, server):
        self.server = server
        self.db = server.db
        self.devices = server.devices
        self.logs = server.logs
        self.blocking = server.blocking
        self.settings = server.settings
        self.wait_info = WaitInfo()
        self.ev_loop = server.ev_loop
        self.exports = server.exports
        self.clock = NodesClockSyncInfo(server.ev_loop)
        self.expose_manager = ExposeManager(server.tcp_server, server.ev_loop)
        self.status_manager = NodeBootupStatusManager(server.tcp_server, self)
        self.filesystems = FilesystemsCache(server.ev_loop, FS_CMD_PATTERN)
        self.vnodes = {}
        self.powersave = PowersaveManager(server)
        self.node_register_kwargs = dict(
            images=server.images.store, dhcpd=server.dhcpd,
            named=server.named, registry=server.registry
        )
        self._cleaning_up = False

    def forget_device(self, mac):
        self.status_manager.forget_device(mac)

    def prepare(self):
        known_hosts_nodes = Path("/var/lib/walt/ssh/known_hosts.nodes")
        known_hosts_nodes.parent.mkdir(parents=True, exist_ok=True)
        pub_key = NODE_SSH_ECDSA_HOST_KEY_PUB_PATH.read_text()
        alg, key = pub_key.split()[:2]
        known_hosts_nodes.write_text(f"walt.node {alg} {key}")

    def restore(self):
        # init powersave
        self.powersave.restore()
        # init nodes bootup status
        self.status_manager.restore()
        # start virtual nodes
        where_sql, where_values = "d.type = 'node' and d.virtual", ()
        for vnode in self.devices.get_multiple_device_info(where_sql, where_values):
            self.start_vnode(vnode)

    def update_node_boot_retries(self, node_mac, retries):
        self.status_manager.update_node_boot_retries(node_mac, retries)

    def update_node_boot_timeout(self, node_mac, timeout):
        self.status_manager.update_node_boot_timeout(node_mac, timeout)

    def record_nodes_boot_start(self, nodes):
        self.status_manager.record_nodes_boot_start(nodes)

    def get_booted_macs(self):
        return self.status_manager.get_booted_macs()

    def terminate_vnode_process(self, node_mac):
        if node_mac in self.vnodes:
            popen, listener = self.vnodes[node_mac]
            popen.close()
            listener.close()
            del self.vnodes[node_mac]

    def cleanup(self):
        self._cleaning_up = True
        # stop nodes bootup monitoring
        self.status_manager.cleanup()
        # stop virtual nodes
        for vnode in self.db.select("devices", type="node", virtual=True):
            print(f"stop vnode {vnode.name}")
            self.terminate_vnode_process(vnode.mac)
        # cleanup filesystem interpreters
        self.filesystems.cleanup()

    def forget_vnode(self, node_mac):
        self.terminate_vnode_process(node_mac)
        # note: the calling code takes care of discarding db data
        # about this vnode (see server.py)

    def register_node(self, mac, model, image_fullname=None):
        if self._cleaning_up:
            return
        handle_registration_request(
            db=self.db,
            devices=self.devices,
            mac=mac,
            model=model,
            image_fullname=image_fullname,
            blocking=self.blocking,
            logs=self.logs,
            exports=self.exports,
            status_manager=self.status_manager,
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
        if self._cleaning_up:
            task.return_result(False)
            return
        req = "BLINK %d" % int(blink_status)
        node = self.get_node_info(requester, node_name)
        if node is None:
            return False  # error already reported
        task.set_async()
        cb_kwargs = dict(requester=requester, task=task)
        node_request(self.ev_loop, (node,), req, self.blink_callback, cb_kwargs)

    def show(self, username, show_all, names_only):
        return show(self, username, show_all, names_only)

    def web_api_list_nodes(self, *args):
        return web_api_list_nodes(self.devices, self.settings, *args)

    def generate_free_mac(self, prefix):
        while True:
            free_mac = f"{prefix}:%02x:%02x:%02x" % (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255),
            )
            if (self.db.select_unique("devices", mac=free_mac) is None and
                self.db.select_unique("vpnauth", vpnmac=free_mac) is None):
                return free_mac  # ok, mac is free

    def generate_vnode_info(self):
        # random mac address generation
        free_mac = self.generate_free_mac("52:54:00")
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
            netmask=node.netmask,
            gateway=node.gateway,
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
        if self._cleaning_up:
            return
        popen = self.vnodes[node_mac][0]
        popen.stdin.write(b'KILL_VM\n')

    def vnode_console_input(self, node_mac, buf):
        if self._cleaning_up:
            return
        # qemu has escape sequences starting with <ctrl-a>. we do not want
        # to let them accessible to the user.
        # to send a <ctrl-a> to the guest, we send <ctrl-a><ctrl-a> to qemu.
        if buf == b"\x01":
            buf = b"\x01\x01"
        popen = self.vnodes[node_mac][0]
        popen.stdin.write(b'INPUT ' + base64.b64encode(buf) + b'\n')

    def vnode_update_vm_setting(self, node_mac, setting_name, setting_value):
        if self._cleaning_up:
            return
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
        return device_info

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
            self.status_manager.reset_boot_retries(nodes)
        reboot_nodes(
            server=self.server,
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

    def parse_node_set(self, requester, node_set, **kwargs):
        device_set = self.devices.parse_device_set(requester, node_set, **kwargs)
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

    def change_nodes_bootup_status(self, *args, **kwargs):
        return self.status_manager.change_nodes_bootup_status(*args, **kwargs)

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
