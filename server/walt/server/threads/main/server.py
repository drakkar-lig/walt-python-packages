#!/usr/bin/env python
import re
import pickle
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.devices.registry import get_device_cls_from_vci_and_mac
from walt.common.tcp import TCPServer
from walt.common.tools import format_sentence_about_nodes
from walt.server.threads.main.blocking import BlockingTasksManager
from walt.server.threads.main.db import ServerDB
from walt.server.threads.main.images.image import format_image_fullname
from walt.server.threads.main.images.manager import NodeImageManager
from walt.server.threads.main.interactive import InteractionManager
from walt.server.threads.main.logs import LogsManager
from walt.server.threads.main.mydocker import DockerClient
from walt.server.threads.main.network.dhcpd import DHCPServer
from walt.server.threads.main.nodes.manager import NodesManager
from walt.server.threads.main.devices.manager import DevicesManager
from walt.server.threads.main.devices.topology import TopologyManager
from walt.server.threads.main.settings_manager import SettingsHandler
from walt.server.threads.main.transfer import TransferManager
from walt.server.threads.main.apisession import APISession
from walt.server.threads.main.network import tftp


class Server(object):

    def __init__(self, ev_loop, ui):
        self.ev_loop = ev_loop
        self.ui = ui
        self.db = ServerDB()
        self.docker = DockerClient()
        self.blocking = BlockingTasksManager()
        self.devices = DevicesManager(self.db)
        self.topology = TopologyManager(self.devices)
        self.dhcpd = DHCPServer(self.db)
        self.images = NodeImageManager(self.db, self.blocking, self.dhcpd, self.docker)
        self.tcp_server = TCPServer(WALT_SERVER_TCP_PORT)
        self.logs = LogsManager(self.db, self.tcp_server, self.blocking, self.ev_loop)
        self.interaction = InteractionManager(\
                        self.tcp_server, self.ev_loop)
        self.transfer = TransferManager(\
                        self.tcp_server, self.ev_loop)
        self.nodes = NodesManager(  tcp_server = self.tcp_server,
                                    ev_loop = self.ev_loop,
                                    db = self.db,
                                    blocking = self.blocking,
                                    images = self.images.store,
                                    dhcpd = self.dhcpd,
                                    docker = self.docker,
                                    devices = self.devices,
                                    topology = self.topology)
        self.settings = SettingsHandler(server=self)

    def prepare(self):
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

    def register_device(self, vci, uci, ip, mac, **kwargs):
        # let's try to identify this device given its mac address
        # and/or the vci field of the DHCP request.
        if uci.startswith('walt.node'):
            auto_id = uci
        elif vci.startswith('walt.node'):
            auto_id = vci
        else:
            auto_id = None
        if auto_id is None:
            device_cls = get_device_cls_from_vci_and_mac(vci, mac)
        else:
            model = auto_id[10:]
            class DevClass:
                MODEL_NAME = model
                WALT_TYPE  = "node"
            device_cls = DevClass
        new_equipment = self.devices.register_device(device_cls,
                    ip = ip, mac = mac, **kwargs)
        if new_equipment and device_cls != None and device_cls.WALT_TYPE == 'node':
            # this is a walt node
            self.nodes.register_node(   mac = mac,
                                        model = device_cls.MODEL_NAME)

    def get_device_info(self, device_mac):
        return dict(self.devices.get_complete_device_info(device_mac)._asdict())

    def rename_device(self, requester, old_name, new_name):
        self.devices.rename(requester, old_name, new_name)
        self.dhcpd.update()
        tftp.update(self.db)

    def device_rescan(self, requester, remote_ip, device_set):
        devices = self.devices.parse_device_set(requester, device_set)
        if devices == None:
            return False   # error already reported
        self.topology.rescan(requester=requester, remote_ip=remote_ip, devices=devices)
        self.dhcpd.update()
        tftp.update(self.db)

    def forget_device(self, device_name):
        self.db.forget_device(device_name)
        self.dhcpd.update()
        # if it's a node and no other node uses its image,
        # this image should be unmounted.
        self.images.store.update_image_mounts()

    def create_vnode(self, requester, name):
        if not self.devices.validate_device_name(requester, name):
            return False
        mac, ip, model = self.nodes.generate_vnode_info()
        vci = 'walt.node.' + model
        # mimic a DHCP request from the node in order to
        # bootstrap the registration procedure (possibly involving
        # the download of a default image...)
        self.register_device(vci, '', ip, mac, name = name, virtual = True)
        # start background vm
        node = self.devices.get_complete_device_info(mac)
        self.nodes.start_vnode(node)
        return True

    def remove_vnode(self, requester, name):
        info = self.nodes.get_virtual_node_info(requester, name)
        if info is None:
            return  # error already reported
        self.nodes.forget_vnode(name)
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

    def image_shell_session_save(self, requester, session, new_name, name_confirmed):
        status = session.save(requester, new_name, name_confirmed)
        if status == 'OK_BUT_REBOOT_NODES':
            image_fullname = format_image_fullname(requester.get_username(), new_name)
            self.nodes.reboot_nodes_for_image(requester, image_fullname)
            status = 'OK_SAVED'
        return status
