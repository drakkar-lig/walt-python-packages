import re
import pickle

from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.devices.registry import get_device_info_from_mac
from walt.common.tcp import TCPServer
from walt.common.formatting import format_sentence
from walt.server.threads.main.blocking import BlockingTasksManager
from walt.server.threads.main.db import ServerDB
from walt.server.threads.main.images.image import format_image_fullname, parse_image_fullname
from walt.server.threads.main.images.manager import NodeImageManager
from walt.server.threads.main.interactive import InteractionManager
from walt.server.threads.main.logs import LogsManager
from walt.server.threads.main.repositories import Repositories
from walt.server.threads.main.network.dhcpd import DHCPServer
from walt.server.threads.main.nodes.manager import NodesManager
from walt.server.threads.main.devices.manager import DevicesManager
from walt.server.threads.main.devices.topology import TopologyManager
from walt.server.threads.main.settings import SettingsManager
from walt.server.threads.main.transfer import TransferManager
from walt.server.threads.main.apisession import APISession
from walt.server.threads.main.network import tftp
from walt.server.threads.main.vpn import VPNManager
from walt.server.threads.main.autocomplete import shell_autocomplete
from walt.server.threads.main.transfer import validate_cp, \
                    format_node_to_booted_image_transfer_cmd

class Server(object):

    def __init__(self, ev_loop, ui):
        self.ev_loop = ev_loop
        self.ui = ui
        self.db = ServerDB()
        self.repositories = Repositories()
        self.blocking = BlockingTasksManager()
        self.devices = DevicesManager(self.db)
        self.topology = TopologyManager(self.devices, self.add_or_update_device)
        self.dhcpd = DHCPServer(self.db, self.ev_loop)
        self.images = NodeImageManager(self)
        self.tcp_server = TCPServer(WALT_SERVER_TCP_PORT)
        self.logs = LogsManager(self.db, self.tcp_server, self.blocking, self.ev_loop)
        self.interaction = InteractionManager(\
                        self.tcp_server, self.ev_loop)
        self.transfer = TransferManager(\
                        self.tcp_server, self.ev_loop)
        self.nodes = NodesManager(tcp_server=self.tcp_server,
                                  ev_loop=self.ev_loop,
                                  db=self.db,
                                  blocking=self.blocking,
                                  images=self.images.store,
                                  dhcpd=self.dhcpd,
                                  repositories=self.repositories,
                                  devices=self.devices,
                                  topology=self.topology)
        self.settings = SettingsManager(server=self)
        self.vpn = VPNManager()

    def prepare(self):
        tftp.prepare()
        self.tcp_server.join_event_loop(self.ev_loop)
        self.db.plan_auto_commit(self.ev_loop)
        # ensure the dhcp server is running,
        # otherwise the switches may have ip addresses
        # outside the WalT network, and we will not be able
        # to communicate with them when trying to update
        # the topology.
        self.dhcpd.update(force=True)
        self.images.prepare()
        self.nodes.prepare()

    def update(self):
        # mount images needed
        self.ui.task_start('Scanning walt images...')
        self.ui.task_running()
        self.images.update(startup = True)
        # restores nodes setup
        self.nodes.restore()
        self.ui.task_done()

    def cleanup(self):
        APISession.cleanup_all()
        self.images.cleanup()
        self.nodes.cleanup()

    def set_image(self, requester, node_set, image_tag):
        nodes = self.nodes.parse_node_set(requester, node_set)
        if nodes == None:
            return False   # error already reported
        return self.images.set_image(requester, nodes, image_tag)

    def add_or_update_device(self, vci='', uci='', ip=None, mac=None, name=None, **kwargs):
        # let's try to identify this device given its mac address
        # and/or the vci field of the DHCP request.
        if uci.startswith('walt.node'):
            auto_id = uci
        elif vci.startswith('walt.node'):
            auto_id = vci
        else:
            auto_id = None
        if auto_id is None:
            info = get_device_info_from_mac(mac)
        else:
            model = auto_id[10:]
            info = {
                'type': 'node',
                'model': model
            }
        kwargs.update(**info)
        if name is not None:
            kwargs.update(name = name)
        new_equipment = self.devices.add_or_update(
                    ip = ip, mac = mac, **kwargs)
        if new_equipment and info.get('type') == 'node':
            # this is a walt node
            self.nodes.register_node(   mac = mac,
                                        model = info.get('model'))

    def get_device_info(self, device_mac):
        return dict(self.devices.get_complete_device_info(device_mac)._asdict())

    def rename_device(self, requester, old_name, new_name):
        self.devices.rename(requester, old_name, new_name)
        self.dhcpd.update()
        tftp.update(self.db, self.images.store)

    def device_rescan(self, requester, task, remote_ip, device_set):
        devices = self.devices.parse_device_set(requester, device_set)
        if devices == None:
            return False   # error already reported
        # make devices pickle-able
        devices = [d._asdict() for d in devices]
        # the result of the task the hub thread submitted to us
        # will not be available right now
        task.set_async()
        # function that will be called when blocking thread has done the job
        def cb(res):
            self.dhcpd.update()
            tftp.update(self.db, self.images.store)
            task.return_result(res)
        self.blocking.rescan_topology(requester, cb, remote_ip=remote_ip, devices=devices)

    def forget_device(self, device_name):
        self.logs.forget_device(device_name)
        self.db.forget_device(device_name)
        self.dhcpd.update()
        # if it's a node and no other node uses its image,
        # this image should be unmounted.
        self.images.store.update_image_mounts()

    def create_vnode(self, requester, task, name):
        if not self.devices.validate_device_name(requester, name):
            return False
        username = requester.get_username()
        if username is None:
            return False    # username already disconnected, give up
        mac, ip, model = self.nodes.generate_vnode_info()
        image_fullname = format_image_fullname(username, model + '-default')
        def on_image_ready():
            requester.set_default_busy_label()
            requester.stdout.write(f'Node {name} is now booting your image "{model}-default".\n')
            requester.stdout.write(f'Use `walt node boot {name} <other-image>` if needed.\n')
            self.create_vnode_using_image(name, mac, ip, model, image_fullname)
        if image_fullname not in self.images.store:
            requester.set_busy_label(f'Cloning image "{model}-default"')
            clonable_link = f'hub:waltplatform/{model}-default:latest'
            task.set_async()
            def callback(clone_result):
                status = clone_result[0]
                if status == 'OK':
                    on_image_ready()
                    task.return_result(True)
                elif status == 'FAILED':
                    task.return_result(False)
                else:
                    requester.stderr.write('Unexpected result from clone operation!\n')
                    task.return_result(False)
            self.blocking.clone_image(requester, callback, clonable_link = clonable_link,
                          force = False, image_name = None)
        else:
            on_image_ready()
            return True

    def create_vnode_using_image(self, name, mac, ip, model, image_fullname):
        # declare node in db
        self.devices.add_or_update(
                type = 'node',
                model = model,
                ip = ip,
                mac = mac,
                name = name,
                virtual = True
        )
        self.nodes.register_node(mac = mac,
                                 model = model,
                                 image_fullname = image_fullname)
        # start background vm
        node = self.devices.get_complete_device_info(mac)
        self.nodes.start_vnode(node)

    def remove_vnode(self, requester, name):
        info = self.nodes.get_virtual_node_info(requester, name)
        if info is None:
            return  # error already reported
        self.nodes.forget_vnode(info.mac)
        self.forget_device(name)

    def count_logs(self, history, streams = None, senders = None, **kwargs):
        unpickled_history = (pickle.loads(e) if e else None for e in history)
        if streams:
            # compute streams ids whose name match the regular expression
            stream_ids = []
            streams_re = re.compile(streams)
            for row in self.db.get_logstream_ids(senders):
                matches = streams_re.findall(row.name)
                if len(matches) > 0:
                    stream_ids.append(str(row.id))
            if len(stream_ids) == 0:
                return 0    # no streams => no logs
            # we can release the constraint on senders since we restrict to
            # their logstreams (cf. stream_ids variable we just computed)
            senders = None
        else:
            stream_ids = None
        return self.db.count_logs(history = unpickled_history,
                                  senders = senders,
                                  stream_ids = stream_ids,
                                  **kwargs)

    def reboot_nodes_after_image_change(self, requester, task_callback, image_fullname):
        nodes = self.nodes.get_nodes_using_image(image_fullname)
        if len(nodes) == 0:
            task_callback(None) # nothing to do
            return
        requester.stdout.write(format_sentence(
                'Trying to reboot %s using this image...\n', [n.name for n in nodes],
                None, 'node', 'nodes'))
        self.nodes.reboot_nodes(requester, task_callback, nodes, False)

    def image_shell_session_save(self, requester, cb_return, session, new_name, name_confirmed):
        image_fullname = format_image_fullname(requester.get_username(), new_name)
        status = session.save(requester, new_name, name_confirmed)
        if status == 'OK_BUT_REBOOT_NODES':
            cb_reboot = lambda res: cb_return('OK_SAVED')
            self.reboot_nodes_after_image_change(requester, cb_reboot, image_fullname)
        else:
            cb_return(status)

    def squash_image(self, requester, task, image_name, confirmed):
        task.set_async()
        def task_callback(status):
            if status == 'OK_BUT_REBOOT_NODES':
                image_fullname = format_image_fullname(requester.get_username(), image_name)
                task_callback_2 = lambda res: task.return_result('OK')
                self.reboot_nodes_after_image_change(requester, task_callback_2, image_fullname)
            else:
                task.return_result(status)
        return self.images.squash(requester = requester,
                                  task_callback = task_callback,
                                  image_name = image_name,
                                  confirmed = confirmed)

    def validate_cp(self, requester, image_or_node_label, src, dst):
        return validate_cp(image_or_node_label, self, requester, src, dst)

    def node_cp_to_booted_image(self, requester, task, node_name, **path_info):
        node_info = self.nodes.get_node_info(requester, node_name)
        if node_info is None:
            return  # error already reported
        fullname, username, image_name = parse_image_fullname(node_info.image)
        session = self.images.create_shell_session(
                                requester, image_name, 'file transfer')
        if session == None:
            return  # issue already reported
        cmd = format_node_to_booted_image_transfer_cmd(
            node_ip = node_info.ip,
            image_fullname = fullname,
            container_name = session.container_name,
            **path_info
        )
        task.set_async()
        # callbacks that will be called when blocking thread has done the job
        def cb_unblock_client(res):
            task.return_result(None)
        def cb(res):
            requester.set_default_busy_label()
            self.image_shell_session_save(
                requester, cb_unblock_client, session, image_name, True)
        requester.set_busy_label('Transfering')
        self.blocking.run_shell_cmd(requester, cb, cmd, shell=True)

    def shell_autocomplete(self, requester, username, argv, debug=False):
        return shell_autocomplete(self, requester, username, argv, debug=debug)
