import os
import random
import shlex
import signal
import subprocess
import sys
from pathlib import Path
from time import time

from walt.common.tools import do
from walt.server.const import SSH_COMMAND
from walt.server.processes.main.filesystem import FilesystemsCache
from walt.server.processes.main.network.netsetup import NetSetup
from walt.server.processes.main.nodes.clock import NodesClockSyncInfo
from walt.server.processes.main.nodes.expose import ExposeManager
from walt.server.processes.main.nodes.netservice import node_request
from walt.server.processes.main.nodes.reboot import reboot_nodes
from walt.server.processes.main.nodes.register \
    import handle_registration_request, restore_interrupted_registration
from walt.server.processes.main.nodes.show import show
from walt.server.processes.main.nodes.wait import WaitInfo
from walt.server.tools import get_server_ip, ip, get_walt_subnet

VNODE_DEFAULT_RAM = "512M"
VNODE_DEFAULT_CPU_CORES = 4
VNODE_DEFAULT_DISKS = 'none'
# We record virtual nodes serial console output here
# (we avoid using the logging system for this in order to avoid adding network traffic)
VNODE_LOG_DIR = Path('/var/lib/walt/logs/vnodes/')
VNODE_PID_PATH = '/var/lib/walt/nodes/%(mac)s/pid'
VNODE_SCREEN_SESSION_PATH = '/var/lib/walt/nodes/%(mac)s/screen_session'

MSG_NOT_VIRTUAL = "WARNING: %s is not a virtual node. IGNORED.\n"

FS_CMD_PATTERN = SSH_COMMAND + ' root@%(fs_id)s "sh"'   # use node_ip as our fs ID

VNODE_CMD = "walt-virtual-node --mac %(mac)s --ip %(ip)s --model %(model)s --hostname %(name)s \
                               --server-ip %(server_ip)s --cpu-cores %(cpu_cores)d --ram %(ram)s \
                               --disks %(disks)s"
CMD_START_VNODE = 'screen -S walt.node.%(hypmac)s -d -m \
                     script -f -t%(ttyrec_file)s.time -c "' + VNODE_CMD + '" %(ttyrec_file)s'
CMD_ADD_SSH_KNOWN_HOST = "  mkdir -p /root/.ssh && ssh-keygen -F %(ip)s || \
                            ssh-keyscan -t ecdsa %(ip)s >> /root/.ssh/known_hosts"

class NodesManager(object):
    def __init__(self, tcp_server, ev_loop, db, blocking, devices, **kwargs):
        self.db = db
        self.devices = devices
        self.blocking = blocking
        self.other_kwargs = kwargs
        self.wait_info = WaitInfo()
        self.ev_loop = ev_loop
        self.clock = NodesClockSyncInfo(ev_loop)
        self.expose_manager = ExposeManager(tcp_server, ev_loop)
        self.filesystems = FilesystemsCache(ev_loop, FS_CMD_PATTERN)

    def prepare(self):
        # set booted flag of all nodes to False for now
        self.db.execute('UPDATE nodes SET booted = false;')
        # prepare the network setup for NAT support
        self.prepare_netsetup()

    def restore(self):
        # start virtual nodes
        for vnode in self.db.select('devices', type = 'node', virtual = True):
            node = self.devices.get_complete_device_info(vnode.mac)
            self.start_vnode(node)

    def prepare_netsetup(self):
        # force-create the chain WALT and assert it is empty
        do("iptables --new-chain WALT")
        do("iptables --flush WALT")
        do("iptables --append WALT --jump DROP")
        # allow traffic on the bridge (virtual <-> physical nodes)
        do("iptables --append FORWARD "
           "--in-interface walt-net --out-interface walt-net "
           "--jump ACCEPT")
        # allow connections back to WalT
        do("iptables --append FORWARD "
           "--out-interface walt-net --match state --state RELATED,ESTABLISHED "
           "--jump ACCEPT")
        # jump to WALT chain for other traffic
        do("iptables --append FORWARD "
           "--in-interface walt-net "
           "--jump WALT")
        # NAT nodes traffic that is allowed to go outside
        do("iptables --table nat --append POSTROUTING "
           "! --out-interface walt-net --source %s "
           "--jump MASQUERADE" % str(get_walt_subnet()))
        # Set the configuration of all NAT-ed nodes
        for node_info in self.db.execute("""\
                SELECT ip FROM nodes
                INNER JOIN devices ON devices.mac = nodes.mac
                WHERE COALESCE((conf->'netsetup')::int, 0) = %d;
                """ % NetSetup.NAT):
            do("iptables --insert WALT --source '%s' --jump ACCEPT" % node_info.ip)

    def get_vnode_screen_session_name(self, node_mac):
        # get screen session
        hypmac = node_mac.replace(':','-')
        try:
            return subprocess.check_output(
                'screen -ls | grep -ow "[[:digit:]]*.walt.node.%(hypmac)s"' % \
                dict(hypmac = hypmac), shell=True).strip().decode(sys.stdout.encoding)
        except subprocess.CalledProcessError:
            # no screen session (killed or not started yet)
            return None

    def try_kill_vnode(self, node_mac):
        session_name = self.get_vnode_screen_session_name(node_mac)
        if session_name is not None:
            pid_path = Path(VNODE_PID_PATH % dict(mac = node_mac))
            try:
                pid = int(pid_path.read_text())
                os.kill(pid, signal.SIGTERM)
            except:
                pass

    def cleanup(self):
        # stop virtual nodes
        for vnode in self.db.select('devices', type = 'node', virtual = True):
            self.try_kill_vnode(vnode.mac)
        self.cleanup_netsetup()
        # cleanup filesystem interpreters
        self.filesystems.cleanup()

    def cleanup_netsetup(self):
        # drop rules set by prepare_netsetup
        do("iptables --table nat --delete POSTROUTING "
           "! --out-interface walt-net --source %s "
           "--jump MASQUERADE" % str(get_walt_subnet()))
        do("iptables --delete FORWARD "
           "--in-interface walt-net "
           "--jump WALT")
        do("iptables --delete FORWARD "
           "--out-interface walt-net --match state --state RELATED,ESTABLISHED "
           "--jump ACCEPT")
        do("iptables --delete FORWARD "
           "--in-interface walt-net --out-interface walt-net "
           "--jump ACCEPT")
        do("iptables --flush WALT")
        do("iptables --delete-chain WALT")

    def forget_vnode(self, node_mac):
        self.try_kill_vnode(node_mac)

    def register_node(self, mac, model, image_fullname = None):
        handle_registration_request(
                db = self.db,
                mac = mac,
                model = model,
                image_fullname = image_fullname,
                blocking = self.blocking,
                **self.other_kwargs
        )

    def restore_interrupted_registration(self, image_fullname):
        restore_interrupted_registration(
                db = self.db,
                image_fullname = image_fullname,
                blocking = self.blocking,
                **self.other_kwargs
        )

    def connect(self, requester, node_name, hide_issues = False):
        nodes_ip = self.get_nodes_ip(
                        requester, node_name)
        if len(nodes_ip) == 0:
            return None # error was already reported
        link = ServerToNodeLink(nodes_ip[0])
        connect_status = link.connect()
        if not connect_status[0]:
            if not hide_issues:
                requester.stderr.write('Error connecting to %s: %s\n' % \
                    (node_name, connect_status[1]))
            return None
        return link

    def blink_callback(self, results, requester, task):
        # we have just one node, so one entry in results
        result_msg = tuple(results.keys())[0]
        node = results[result_msg][0]
        if result_msg == 'OK':
            task.return_result(True)
        else:
            requester.stderr.write('Blink request to %s failed: %s\n' % \
                    (node.name, result_msg))
            task.return_result(False)

    def blink(self, requester, task, node_name, blink_status):
        req = 'BLINK %d' % int(blink_status)
        node = self.get_node_info(requester, node_name)
        if node == None:
            return False # error already reported
        task.set_async()
        cb_kwargs = dict(requester = requester, task = task)
        node_request(self.ev_loop, (node,), req, self.blink_callback, cb_kwargs)

    def show(self, username, show_all, names_only):
        return show(self.db, username, show_all, names_only)

    def generate_vnode_info(self):
        # random mac address generation
        while True:
            free_mac = "52:54:00:%02x:%02x:%02x" % (
                random.randint(0, 255),
                random.randint(0, 255),
                random.randint(0, 255),
            )
            if self.db.select_unique('devices', mac = free_mac) is None:
                break   # ok, mac is free
        # find a free ip
        subnet = get_walt_subnet()
        free_ips = list(subnet.hosts())
        free_ips.pop(0)     # first IP is for WalT server
        for item in self.db.execute(\
                'SELECT ip FROM devices WHERE ip IS NOT NULL'):
            device_ip = ip(item.ip)
            if device_ip in subnet and device_ip in free_ips:
                free_ips.remove(device_ip)
        free_ip = str(free_ips[0])
        return free_mac, free_ip, 'pc-x86-64'

    def start_vnode(self, node):
        # in case a screen session already exists for this vnode
        # (e.g. walt server process was killed), kill it
        self.try_kill_vnode(node.mac)
        # start vnode
        VNODE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        hypmac = node.mac.replace(':', '-')
        print(VNODE_CMD)
        cmd = CMD_START_VNODE % dict(
            mac = node.mac,
            hypmac = hypmac,
            ip = node.ip,
            model = node.model,
            name = node.name,
            server_ip = get_server_ip(),
            cpu_cores = node.conf.get('cpu.cores', VNODE_DEFAULT_CPU_CORES),
            ram = node.conf.get('ram', VNODE_DEFAULT_RAM),
            disks = node.conf.get('disks', VNODE_DEFAULT_DISKS),
            ttyrec_file = VNODE_LOG_DIR / (hypmac + str(int(time())) + '.tty')
        )
        print(cmd)
        subprocess.Popen(shlex.split(cmd))

    def get_node_info(self, requester, node_name):
        device_info = self.devices.get_device_info(requester, node_name)
        if device_info == None:
            return None # error already reported
        device_type = device_info.type
        if device_type != 'node':
            requester.stderr.write('%s is not a node, it is a %s.\n' % \
                                    (node_name, device_type))
            return None
        return self.devices.get_complete_device_info(device_info.mac)

    def get_virtual_node_info(self, requester, node_name):
        node = self.get_node_info(requester, node_name)
        if node is None:
            return None     # error already reported
        if not node.virtual:
            requester.stderr.write(\
                'FAILED: %s is a real node (not virtual).\n' % node_name)
            return None
        return node

    def get_node_ip(self, requester, node_name):
        node_info = self.get_node_info(requester, node_name)
        if node_info == None:
            return None # error already reported
        if node_info.ip == None:
            self.notify_unknown_ip(requester, node_name)
        return node_info.ip

    def get_nodes_ip(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return () # error already reported
        return tuple(node.ip for node in nodes)

    def get_nodes_using_image(self, image_fullname):
        nodes = self.db.select('nodes', image = image_fullname)
        return tuple(
                self.devices.get_complete_device_info(n.mac)
                for n in nodes)

    def get_node_models_using_image(self, image_fullname):
        return set(node.model for node in \
                   self.db.select('nodes', image = image_fullname))

    def prepare_ssh_access_for_ip(self, ip):
        cmd = CMD_ADD_SSH_KNOWN_HOST % dict(ip = ip)
        do(cmd, shell=True)

    def prepare_ssh_access(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return
        for node in nodes:
            self.prepare_ssh_access_for_ip(node.ip)

    def reboot_node_set(self, requester, task, node_set, hard_only):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None  # error already reported
        task.set_async()
        self.reboot_nodes(requester, task.return_result, nodes, hard_only)

    def reboot_nodes(self, requester, task_callback, nodes, hard_only):
        # first, we pass the 'booted' flag of all nodes to false
        # (if we manage to reboot them, they will be unreachable
        #  for a little time; if we do not manage to reboot them,
        #  this probably means they are down, thus not booted...)
        for node in nodes:
            self.db.update('nodes', 'mac', mac = node.mac, booted = False);
        self.db.commit()
        reboot_nodes(   nodes_manager = self,
                        blocking = self.blocking,
                        ev_loop = self.ev_loop,
                        requester = requester,
                        task_callback = task_callback,
                        nodes = nodes,
                        hard_only = hard_only)

    def parse_node_set(self, requester, node_set):
        device_set = self.devices.parse_device_set(requester, node_set)
        if device_set is None:
            return None
        for device_info in device_set:
            if device_info.type != "node":
                requester.stderr.write('%s is not a node, it is a %s.\n' %
                                       (device_info.name, device_info.type))
                return None
        return device_set

    def wait(self, requester, task, node_set):
        nodes = self.parse_node_set(requester, node_set)
        self.wait_info.wait(requester, task, nodes)

    def node_bootup_event(self, node_name):
        node_info = self.get_node_info(None, node_name)
        # update booted flag in db
        self.db.update('nodes', 'mac', mac=node_info.mac, booted=True)
        self.db.commit()
        # unblock any related "walt node wait" command.
        self.wait_info.node_bootup_event(node_info)

    def develop_node_set(self, requester, node_set):
        nodes = self.parse_node_set(requester, node_set)
        if nodes == None:
            return None
        return self.devices.as_device_set(n.name for n in nodes)

    def validate_cp_entity(self, requester, node_name, index, **info):
        if self.get_node_info(requester, node_name) is None:
            return 'FAILED'
        else:
            return 'OK'

    def get_node_filesystem(self, requester, node_name):
        node_ip = self.get_node_ip(requester, node_name)
        if node_ip is None:
            return None
        self.prepare_ssh_access_for_ip(node_ip)
        return self.filesystems[node_ip]

    def get_cp_entity_filesystem(self, requester, node_name, **info):
        return self.get_node_filesystem(requester, node_name)

    def get_cp_entity_attrs(self, requester, node_name, **info):
        owned = not self.devices.includes_devices_not_owned(requester, node_name, True)
        node_info = self.get_node_info(requester, node_name)
        return dict(node_name = node_info.name,
                    node_ip = node_info.ip,
                    node_image = node_info.image,
                    node_owned = owned)