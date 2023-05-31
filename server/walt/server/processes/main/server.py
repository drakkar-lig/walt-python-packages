import re
from pathlib import Path

from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.devices.registry import get_device_info_from_mac
from walt.common.formatting import format_sentence
from walt.common.tcp import TCPServer
from walt.common.tools import format_image_fullname, parse_image_fullname
from walt.server import conf
from walt.server.process import SyncRPCProcessConnector
from walt.server.processes.main.apisession import APISession
from walt.server.processes.main.autocomplete import shell_autocomplete
from walt.server.processes.main.blocking import BlockingTasksManager
from walt.server.processes.main.devices.manager import DevicesManager
from walt.server.processes.main.images.manager import NodeImageManager
from walt.server.processes.main.interactive import InteractionManager
from walt.server.processes.main.logs import LogsManager
from walt.server.processes.main.network import tftp
from walt.server.processes.main.network.dhcpd import DHCPServer
from walt.server.processes.main.nodes.manager import NodesManager
from walt.server.processes.main.registry import WalTLocalRegistry
from walt.server.processes.main.settings import SettingsManager
from walt.server.processes.main.transfer import (
    TransferManager,
    format_node_to_booted_image_transfer_cmd,
    validate_cp,
)
from walt.server.processes.main.unix import UnixSocketServer
from walt.server.processes.main.vpn import VPNManager
from walt.server.processes.main.workflow import Workflow

KVM_DEV_FILE = Path("/dev/kvm")


class Server(object):
    def __init__(self, ev_loop):
        self.ev_loop = ev_loop
        self.db = SyncRPCProcessConnector(label="main-to-db")
        self.registry = WalTLocalRegistry()
        self.blocking = BlockingTasksManager(self)
        self.tcp_server = TCPServer(WALT_SERVER_TCP_PORT)
        self.logs = LogsManager(self.db, self.tcp_server, self.blocking, self.ev_loop)
        self.devices = DevicesManager(self)
        self.dhcpd = DHCPServer(self.db, self.ev_loop)
        self.images = NodeImageManager(self)
        self.interaction = InteractionManager(self.tcp_server, self.ev_loop)
        self.unix_server = UnixSocketServer()
        self.transfer = TransferManager(self.tcp_server, self.ev_loop)
        self.nodes = NodesManager(self)
        self.settings = SettingsManager(server=self)
        self.vpn = VPNManager()

    def prepare(self):
        self.logs.prepare()
        self.logs.catch_std_streams()
        self.registry.prepare()
        tftp.prepare()
        self.tcp_server.prepare(self.ev_loop)
        self.unix_server.prepare(self.ev_loop)
        # ensure the dhcp server is running,
        # otherwise the switches may have ip addresses
        # outside the WalT network, and we will not be able
        # to communicate with them when trying to update
        # the topology.
        self.dhcpd.update(force=True)
        self.images.prepare()
        self.devices.prepare()
        self.nodes.prepare()

    def update(self):
        # mount images needed
        self.images.update(startup=True)
        # enable PoE if some ports remained off
        self.blocking.restore_poe_on_all_ports()
        # restores nodes setup
        self.nodes.restore()

    def cleanup(self):
        APISession.cleanup_all()
        tftp.cleanup(self.db)
        self.images.cleanup()
        self.nodes.cleanup()
        self.devices.cleanup()
        self.logs.logs_to_db.flush()

    def get_registries(self):
        return tuple(
            (reg_info["label"], reg_info["description"])
            for reg_info in conf["registries"]
        )

    def set_image(self, requester, node_set, image_tag):
        nodes = self.nodes.parse_node_set(requester, node_set)
        if nodes is None:
            return False  # error already reported
        return self.images.set_image(requester, nodes, image_tag)

    def cleanup_device_name(self, name):
        return re.sub("[^a-zA-Z0-9-]+", "-", name.split(".")[0])

    def add_or_update_device(
        self, vci="", uci="", ip=None, mac=None, name=None, **kwargs
    ):
        # let's try to identify this device given its mac address
        # and/or the vci field of the DHCP request.
        if uci.startswith("walt.node"):
            auto_id = uci
        elif vci.startswith("walt.node"):
            auto_id = vci
        else:
            auto_id = None
        if auto_id is None:
            info = get_device_info_from_mac(mac)
            info["type"] = info.get("type", "unknown")
        else:
            model = auto_id[10:]
            info = {"type": "node", "model": model}
        kwargs.update(**info)
        if name is not None:
            name = self.cleanup_device_name(name)
            if self.devices.validate_device_name(None, name):
                # name seems meaningful...
                kwargs.update(name=name)
        # what is the current status of this device in db?
        db_info = self.db.select_unique("devices", mac=mac)
        if db_info is None:
            status = "new"
        else:
            status = db_info.type
        # new nodes whose default image is not available yet are first recorded
        # as simple devices of unknown type because downloading their default
        # image may fail.
        if status in ("new", "unknown") and kwargs["type"] == "node":
            image_fullname = self.images.store.get_default_image_fullname(info["model"])
            if image_fullname not in self.images.store:
                kwargs["type"] = "unknown"
        self.devices.add_or_update(ip=ip, mac=mac, **kwargs)
        if status in ("new", "unknown") and info["type"] == "node":
            # register the walt node or convert the unknown device to a walt node
            self.nodes.register_node(mac=mac, model=info.get("model"))
        self.dhcpd.update()

    def get_device_info(self, device_mac):
        return dict(self.devices.get_complete_device_info(device_mac)._asdict())

    def rename_device(self, requester, old_name, new_name):
        result = self.devices.rename(requester, old_name, new_name)
        if result is True:
            self.dhcpd.update()
            tftp.update(self.db, self.images.store)
        return result

    def device_rescan(self, requester, task, remote_ip, device_set):
        devices = self.devices.parse_device_set(requester, device_set)
        if devices is None:
            return False  # error already reported
        # the result of the task the hub process submitted to us
        # will not be available right now
        task.set_async()

        # function that will be called when blocking process has done the job
        def cb(res):
            self.dhcpd.update()
            tftp.update(self.db, self.images.store)
            task.return_result(res)

        self.blocking.rescan_topology(
            requester, cb, remote_ip=remote_ip, devices=devices
        )

    def forget_device(self, requester, task, device_name):
        device = self.devices.get_device_info(requester, device_name)
        if device is None:
            return False
        task.set_async()
        # note: if it's a node and no other node uses its image,
        # this image should be unmounted.
        wf = Workflow(
            [
                self.nodes.powersave.wf_forget_device,
                self.wf_forget_device_other_steps,
                self.images.store.wf_update_image_mounts,
                self.wf_unblock_client,
            ],
            requester=requester,
            device=device,
            task=task,
        )
        wf.run()

    def wf_forget_device_other_steps(self, wf, task, device, **env):
        self.logs.forget_device(device)
        self.db.forget_device(device.name)
        self.dhcpd.update()
        wf.next()

    def wf_unblock_client(self, wf, task, **env):
        task.return_result(True)
        wf.next()

    def create_vnode(self, requester, task, name):
        if not KVM_DEV_FILE.exists():
            requester.stderr.write(
                "Failed because virtualization is not enabled on server CPU"
                f" (missing {KVM_DEV_FILE}).\n"
            )
            return False
        if not self.devices.validate_device_name(requester, name):
            return False
        username = requester.get_username()
        if username is None:
            return False  # username already disconnected, give up
        mac, ip, model = self.nodes.generate_vnode_info()
        default_image_fullname = format_image_fullname(
            "waltplatform", model + "-default"
        )

        def on_default_image_ready():
            default_image_labels = self.images.store[default_image_fullname].labels
            image_name = default_image_labels.get("walt.image.preferred-name")
            if image_name is None:
                # no 'preferred-name' tag, reuse name of default image
                image_name = model + "-default"
            user_image_fullname = format_image_fullname(username, image_name)
            if user_image_fullname not in self.images.store:
                self.registry.tag(default_image_fullname, user_image_fullname)
                self.images.store.register_image(user_image_fullname)
                requester.stdout.write(
                    f'Default image for {model} was saved as "{image_name}" in your'
                    " working set.\n"
                )
            requester.set_busy_label("Registering virtual node")
            self.create_vnode_using_image(name, mac, ip, model, user_image_fullname)
            requester.set_default_busy_label()
            requester.stdout.write(
                f'Node {name} is now booting your image "{image_name}".\n'
            )
            requester.stdout.write(
                f"Use `walt node boot {name} <other-image>` if needed.\n"
            )

        if default_image_fullname not in self.images.store:
            requester.set_busy_label(f'Downloading default image for "{model}"')
            task.set_async()

            def callback(pull_result):
                if pull_result[0]:
                    on_default_image_ready()
                    task.return_result(True)
                else:
                    failure = pull_result[1]
                    requester.stderr.write(failure + "\n")
                    task.return_result(False)

            self.blocking.pull_image(requester, default_image_fullname, callback)
        else:
            on_default_image_ready()
            return True

    def create_vnode_using_image(self, name, mac, ip, model, image_fullname):
        # declare node in db
        self.devices.add_or_update(
            type="node", model=model, ip=ip, mac=mac, name=name, virtual=True
        )
        self.nodes.register_node(mac=mac, model=model, image_fullname=image_fullname)
        # start background vm
        # note: create_vnode_using_image() is called after the default image
        # is downloaded, so we know register_node() completed its process
        # synchronously and we can proceed with the following steps.
        node = self.devices.get_complete_device_info(mac)
        self.nodes.start_vnode(node)

    def remove_vnode(self, requester, task, name):
        info = self.nodes.get_virtual_node_info(requester, name)
        if info is None:
            return False  # error already reported
        self.nodes.forget_vnode(info.mac)
        return self.forget_device(requester, task, name)

    def reboot_nodes_after_image_change(self, requester, task_callback, image_fullname):
        nodes = self.nodes.get_nodes_using_image(image_fullname)
        if len(nodes) == 0:
            # nothing to do
            task_callback("OK")
            return
        requester.stdout.write(
            format_sentence(
                "Trying to reboot %s using this image...\n",
                [n.name for n in nodes],
                None,
                "node",
                "nodes",
            )
        )
        self.nodes.reboot_nodes(requester, task_callback, nodes, False)

    def image_shell_session_save(
        self, requester, cb_return, session, image_fullname, name_confirmed
    ):
        def cb_handle_return_status(status):
            if status == "OK_BUT_REBOOT_NODES":

                def cb_reboot(res):
                    return cb_return("OK_SAVED")

                self.reboot_nodes_after_image_change(
                    requester, cb_reboot, image_fullname
                )
            else:
                cb_return(status)

        session.save(
            self.blocking,
            requester,
            image_fullname,
            name_confirmed,
            cb_handle_return_status,
        )

    def squash_image(self, requester, task, image_name, confirmed):
        task.set_async()

        def task_callback(status):
            if status == "OK_BUT_REBOOT_NODES":
                image_fullname = format_image_fullname(
                    requester.get_username(), image_name
                )

                def task_callback_2(res):
                    return task.return_result("OK")

                self.reboot_nodes_after_image_change(
                    requester, task_callback_2, image_fullname
                )
            else:
                task.return_result(status)

        return self.images.squash(
            requester=requester,
            task_callback=task_callback,
            image_name=image_name,
            confirmed=confirmed,
        )

    def validate_cp(self, requester, image_or_node_label, src, dst):
        return validate_cp(image_or_node_label, self, requester, src, dst)

    def node_cp_to_booted_image(
        self, requester, task, api_session, node_name, **path_info
    ):
        node_info = self.nodes.get_node_info(requester, node_name)
        if node_info is None:
            return  # error already reported
        fullname, username, image_name = parse_image_fullname(node_info.image)
        session = self.images.create_shell_session(
            requester, image_name, "file transfer"
        )
        if session is None:
            return  # issue already reported
        # ensure session.cleanup() will be called when client disconnects
        api_session.register_session_object(session)
        cmd = format_node_to_booted_image_transfer_cmd(
            node_ip=node_info.ip,
            image_fullname=fullname,
            container_name=session.container_name,
            **path_info,
        )
        task.set_async()

        # callbacks that will be called when blocking process has done the job
        def cb_unblock_client(res):
            task.return_result(None)

        def cb(res):
            requester.set_default_busy_label()
            self.image_shell_session_save(
                requester, cb_unblock_client, session, fullname, True
            )

        requester.set_busy_label("Transfering")
        self.blocking.run_shell_cmd(requester, cb, cmd, shell=True)

    def shell_autocomplete(self, requester, username, argv, debug=False):
        return shell_autocomplete(self, requester, username, argv, debug=debug)
