import functools
import io
import re
from pathlib import Path
from time import time
from zipfile import ZipFile

from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.devices.registry import get_device_info_from_mac
from walt.common.formatting import format_sentence
from walt.common.tcp import TCPServer
from walt.common.tools import do, format_image_fullname, parse_image_fullname
from walt.common.version import __version__
from walt.server import conf
from walt.server.popen import BetterPopen
from walt.server.const import (
    NODE_SSH_ECDSA_HOST_KEY_PATH,
    NODE_DROPBEAR_ECDSA_HOST_KEY_PATH,
)
from walt.server.processes.main.apisession import APISession
from walt.server.processes.main.autocomplete import shell_autocomplete
from walt.server.processes.main.devices.manager import DevicesManager
from walt.server.processes.main.exports import FilesystemsExporter
from walt.server.processes.main.images.manager import NodeImageManager
from walt.server.processes.main.interactive import InteractionManager
from walt.server.processes.main.logs import LogsManager
from walt.server.processes.main.network.dhcpd import DHCPServer
from walt.server.processes.main.network.named import DNSServer
from walt.server.processes.main.nodes.manager import NodesManager
from walt.server.processes.main.nodes.register import is_currently_registering_mac
from walt.server.processes.main.registry import WalTLocalRegistry
from walt.server.processes.main.settings import SettingsManager, PortSettingsManager
from walt.server.processes.main.devices.expose import ExposeManager
from walt.server.processes.main.transfer import (
    TransferManager,
    format_node_to_booted_image_transfer_cmd,
    validate_cp,
)
from walt.server.processes.main.unix import UnixSocketServer
from walt.server.processes.main.vpn import VPNManager
from walt.server.processes.main.poe import PoEManager
from walt.server.workflow import Workflow
from walt.server.tools import np_record_to_dict

KVM_DEV_FILE = Path("/dev/kvm")


class Server(object):
    def __init__(self, ev_loop, db, blocking):
        self.ev_loop = ev_loop
        self.db = db
        self.db.configure()
        self.registry = WalTLocalRegistry()
        self.blocking = blocking
        self.blocking.configure(self)
        self.tcp_server = TCPServer(WALT_SERVER_TCP_PORT)
        self.logs = LogsManager(self.db, self.tcp_server, self.ev_loop)
        self.devices = DevicesManager(self)
        self.dhcpd = DHCPServer(self.db, self.ev_loop)
        self.named = DNSServer(self.db, self.ev_loop)
        self.exports = FilesystemsExporter(self)
        self.images = NodeImageManager(self)
        self.interaction = InteractionManager(self.tcp_server, self.ev_loop)
        self.unix_server = UnixSocketServer(self)
        self.transfer = TransferManager(self.tcp_server, self.ev_loop)
        self.settings = SettingsManager(server=self)
        self.nodes = NodesManager(self)
        self.port_settings = PortSettingsManager(server=self)
        self.vpn = VPNManager(server=self)
        self.expose = ExposeManager(server=self)
        self.poe = PoEManager(server=self)

    def prepare_keys(self):
        # Note: although they are stored in a different format,
        # dropbear and sshd host keys must be the same, because
        # a node may be booted first with an OS image equipped
        # with openssh (e.g., a debian image) and later be rebooted
        # with an OS image equipped with dropbear (e.g. openwrt).
        # So we generate the openssh key with ssh-keygen and then
        # convert it with dropbearconvert.
        if not NODE_SSH_ECDSA_HOST_KEY_PATH.exists():
            NODE_SSH_ECDSA_HOST_KEY_PATH.parent.mkdir(
                    parents=True, exist_ok=True)
            # note: this also generates the .pub file
            do(f"ssh-keygen -t ecdsa -N '' -f {NODE_SSH_ECDSA_HOST_KEY_PATH}")
        if not NODE_DROPBEAR_ECDSA_HOST_KEY_PATH.exists():
            NODE_DROPBEAR_ECDSA_HOST_KEY_PATH.parent.mkdir(
                    parents=True, exist_ok=True)
            do("dropbearconvert openssh dropbear "
              f"{NODE_SSH_ECDSA_HOST_KEY_PATH} {NODE_DROPBEAR_ECDSA_HOST_KEY_PATH}")

    def prepare(self):
        self.prepare_keys()
        self.logs.prepare()
        self.logs.catch_std_streams()
        self.registry.prepare()
        self.tcp_server.prepare(self.ev_loop)
        self.unix_server.prepare(self.ev_loop)
        # ensure the dhcp server is running,
        # otherwise the switches may have ip addresses
        # outside the WalT network, and we will not be able
        # to communicate with them when trying to update
        # the topology.
        self.dhcpd.update()
        self.named.update(force=True)
        self.devices.prepare()
        self.nodes.prepare()
        # restore permanent expose sockets
        self.expose.restore()

    def _wf_after_exports_update(self, wf, **env):
        # let walt-server-dhcpd leave the degraded mode
        self.dhcpd.start_heartbeat()
        # enable PoE if some ports remained off
        self.poe.restore_poe_on_all_ports()
        # restores nodes setup
        self.nodes.restore()
        # continue workflow
        wf.next()

    def update(self):
        self.images.store.resync_from_db()
        wf = Workflow([self.exports.wf_prepare,
                       self.exports.wf_update,
                       self._wf_after_exports_update])
        wf.run()

    def cleanup(self):
        self.unix_server.shutdown()
        self.tcp_server.shutdown()
        self.expose.cleanup()
        APISession.cleanup_all()
        self.images.store.filesystems.cleanup()
        self.exports.cleanup()
        self.nodes.cleanup()
        self.devices.cleanup()
        # continue event loop until all popens and workflows
        # have ended
        t0 = time()
        loop_condition = functools.partial(self.continue_evloop, t0)
        if loop_condition():
            self.ev_loop.loop(loop_condition)
        self.logs.logs_to_db.flush()

    def continue_evloop(self, t0):
        if (BetterPopen.can_end_evloop() and
            Workflow.can_end_evloop() and
            not self.ev_loop.has_bg_processes()):
            return False  # loop can be stopped
        elif time() - t0 > 10.0:
            Workflow.cleanup_remaining_workflows()
            return False  # loop should be forcibly stopped
        else:
            return True   # loop should continue

    def get_registries(self):
        return tuple(
            (reg_info["label"], reg_info["description"])
            for reg_info in conf["registries"]
        )

    def set_image(self, requester, task, node_set, image_tag):
        nodes = self.nodes.parse_node_set(requester, node_set)
        if nodes is None:
            return False  # error already reported
        return self.images.set_image(requester, task, nodes, image_tag)

    def cleanup_device_name(self, name):
        return re.sub("[^a-zA-Z0-9-]+", "-", name.split(".")[0])

    def add_or_update_device(self, task,
        mac=None, ip=None, type="unknown",
        model=None, name=None, tmp_ip=None
    ):
        # if the node is in a boot-loop waiting for the registration
        # procedure to complete (includes setting up the OS image),
        # return the temporary IP immediately.
        already_registering = is_currently_registering_mac(mac)
        if already_registering:
            assert tmp_ip is not None
            return tmp_ip
        # cleanup name and model inputs
        if name is not None:
            name = self.cleanup_device_name(name)
            if not self.devices.validate_device_name(None, name):
                name = None  # name does not seem valid
        if model is not None:
            if len(model) == 0:
                model = None
        # what is the current status of this device in db?
        db_info = self.db.select_unique("devices", mac=mac)
        if db_info is None:
            status = "new"
        else:
            status = db_info.type
        # New nodes whose default image is not available yet are first recorded
        # as simple devices of unknown type because downloading their default
        # image may fail. We allocate a temporary ip to them, different from
        # their final ip, to handle the boot loop correctly until the OS
        # is ready to be booted and the board restarts booting with a new
        # DHCP DISCOVER request.
        if status in ("new", "unknown") and type == "node":
            # prepare the task for workflow mode
            if task:
                task.set_async()
            def wf_reply_task(wf, task, reply_ip, **env):
                if task:
                    task.return_result(reply_ip)
                wf.next()
            # check if we have everything ready to expose a default OS for
            # this new node, or if we should direct it to the boot-loop files
            # with a temporary IP address.
            fullname = self.images.store.get_default_image_fullname(model)
            os_ready = (fullname in self.images.store and
                        self.images.store[fullname].in_use())
            if os_ready:
                self.devices.add_or_update(ip = ip,
                                           mac = mac,
                                           type = "node",
                                           image = fullname,
                                           model = model,
                                           name = name)
                wf_steps = [
                    self.nodes.wf_register_node,  # short, OS is ready
                    wf_reply_task,                # reply with final ip
                ]
                reply_ip = ip
            else:
                # the OS image is not ready, we'll first record the node as
                # an unknown device, let the node enter a boot-loop mode by
                # returning a temporary IP, and we will set up the OS image
                # asynchronously.
                assert tmp_ip is not None
                if status == "new":
                    self.devices.add_or_update(ip = ip,
                                               mac = mac,
                                               type = "unknown",
                                               name = name)
                wf_steps = [
                    wf_reply_task,                # reply early with tmp IP
                    self.nodes.wf_register_node,  # long operation
                ]
                reply_ip = tmp_ip
            # run the workflow
            wf = Workflow(wf_steps,
                          task = task,
                          mac = mac,
                          model = model,
                          reply_ip = reply_ip,
            )
            wf.run()
        else:
            # not a new node
            modified = self.devices.add_or_update(
                ip = ip,
                mac = mac,
                type = type,
                model = model,
                name = name)
            if modified:
                self.dhcpd.update()
                self.named.update()
            return ip

    def rename_device(self, requester, old_name, new_name):
        device = self.devices.rename(requester, old_name, new_name)
        if device is not None:
            self.dhcpd.update()
            self.named.update()
            self.exports.trigger_update()
            if device.type == "node" and device.virtual:
                self.nodes.vnode_rename(device.mac, new_name)
            return True
        else:
            return False

    def device_rescan(self, requester, task, device_set):
        devices = self.devices.parse_device_set(requester, device_set)
        if devices is None:
            return False  # error already reported
        # the result of the task the hub process submitted to us
        # will not be available right now
        task.set_async()
        # 1. restore poe on switch ports
        # 2. let the blocking process do its job
        # 3. update network daemons and unblock the client
        wf = Workflow([self.poe.wf_rescan_restore_poe_on_switch_ports,
                       self._wf_device_rescan_blocking,
                       self._wf_device_rescan_save_result,
                       self._wf_device_rescan_update_services,
                       self._wf_device_rescan_return_result])
        wf.update_env(requester=requester,
                      devices=devices,
                      task=task)
        wf.run()

    def _wf_device_rescan_blocking(self, wf, requester, devices, **env):
        self.blocking.rescan_topology(
            requester, wf.next, devices=devices
        )

    def _wf_device_rescan_save_result(self, wf, res, **env):
        wf.update_env(rescan_res=res)
        wf.next()

    def _wf_device_rescan_update_services(self, wf, **env):
        self.dhcpd.update()
        self.named.update()
        wf.insert_steps([self.exports.wf_update])
        wf.next()

    def _wf_device_rescan_return_result(self, wf, rescan_res, task, **env):
        task.return_result(rescan_res)
        wf.next()   # end the workflow

    def report_lldp_neighbor(self, remote_ip, sw_mac, sw_port_lldp_label):
        # check arguments are valid
        node_info = self.db.select_unique("devices", type="node", ip=remote_ip)
        if node_info is None:
            return
        sw_info = self.db.select_unique("devices", mac=sw_mac)
        if sw_info is None:
            return
        # if neighbor device type was unknown, auto-convert to "switch"
        if sw_info.type == "unknown":
            logline=(f"Node {node_info.name} is connected on {sw_info.name}, "
                     f"so {sw_info.name} is a switch.")
            self.logs.platform_log("devices", line=logline)
            sw_info = np_record_to_dict(sw_info)
            sw_info.update(type="switch")
            self.devices.add_or_update(**sw_info)
            # note: we know the switch has its lldp.explore=false by default
            return
        # if lldp.explore=false, we cannot do more
        if sw_info.conf.get("lldp.explore", False) is False:
            return
        # for the rest, call self.blocking
        self.blocking.report_lldp_neighbor(
                sw_mac=sw_mac,
                sw_ip=sw_info.ip,
                sw_name=sw_info.name,
                sw_port_lldp_label=sw_port_lldp_label,
                node_mac=node_info.mac,
                node_name=node_info.name)

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
                self.exports.wf_update,
                self.wf_unblock_client,
            ],
            requester=requester,
            device=device,
            task=task,
        )
        wf.run()

    def wf_forget_device_other_steps(self, wf, task, device, **env):
        self.logs.forget_device(device)
        self.db.forget_device(device.mac)
        self.dhcpd.update()
        self.named.update()
        self.nodes.forget_device(device.mac)
        wf.next()

    def wf_unblock_client(self, wf, task, task_result=True, **env):
        task.return_result(task_result)
        wf.next()

    def wf_pull_image(self, wf,
                      requester, model, default_image_fullname, **env):
        requester.set_busy_label(f'Downloading default image for "{model}"')
        self.blocking.pull_image(requester, default_image_fullname, wf.next)

    def wf_after_pull_image(self, wf, pull_result, requester, task, **env):
        if pull_result[0]:
            wf.next()
        else:
            failure = pull_result[1]
            requester.stderr.write(failure + "\n")
            task.return_result(False)
            wf.interrupt()

    def wf_tag_default_image_to_user(self, wf, requester, username,
                                     default_image_fullname, model, **env):
        labels = self.images.store[default_image_fullname].labels
        image_name = labels.get("walt.image.preferred-name")
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
        wf.update_env(image_name=image_name,
                      image_fullname=user_image_fullname)
        wf.next()

    def wf_add_vnode_in_db(self, wf, requester, mac, ip, model,
                           name, image_fullname, **env):
        requester.set_busy_label("Registering virtual node")
        self.devices.add_or_update(
            type="node", model=model, ip=ip, mac=mac, name=name, virtual=True,
            image=image_fullname
        )
        wf.next()

    def wf_start_vnode(self, wf, requester, mac, name, image_name, **env):
        node = self.devices.get_device_info(mac=mac)
        self.nodes.start_vnode(node)
        requester.set_default_busy_label()
        requester.stdout.write(
            f'Node {name} is now booting your image "{image_name}".\n'
        )
        requester.stdout.write(
            f"Use `walt node boot {name} <other-image>` if needed.\n"
        )
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
        mac, ip, model = self.nodes.generate_vnode_info(requester)
        if ip is None:
            return False
        default_image_fullname = format_image_fullname(
            "waltplatform", model + "-default"
        )
        # run the task as an async workflow
        task.set_async()
        wf_steps = []
        if default_image_fullname not in self.images.store:
            wf_steps += [self.wf_pull_image, self.wf_after_pull_image]
        wf_steps += [
            self.wf_tag_default_image_to_user,
            self.wf_add_vnode_in_db,
            self.nodes.wf_register_node,
            self.wf_start_vnode,
            self.wf_unblock_client
        ]
        wf = Workflow(wf_steps,
                      requester=requester,
                      task=task,
                      username=username,
                      name=name,
                      mac=mac,
                      ip=ip,
                      model=model,
                      default_image_fullname=default_image_fullname,
        )
        wf.run()

    def remove_vnode(self, requester, task, name):
        info = self.nodes.get_virtual_node_info(requester, name)
        if info is None:
            return False  # error already reported
        self.nodes.forget_vnode(info.mac)
        return self.forget_device(requester, task, name)

    def reboot_nodes_after_image_change(self,
            requester, task_callback, *image_fullnames):
        where_sql = "n.image IN (" + ",".join(["%s"] * len(image_fullnames)) + ")"
        nodes = self.devices.get_multiple_device_info(where_sql, image_fullnames)
        if nodes.size == 0:
            # nothing to do
            task_callback("OK")
            return
        if len(image_fullnames) > 1:
            images_desc = "these images"
        else:
            images_desc = "this image"
        requester.stdout.write(
            format_sentence(
                f"Trying to reboot %s using {images_desc}...\n",
                nodes.name,
                None,
                "node",
                "nodes",
            )
        )
        self.nodes.reboot_nodes(requester, task_callback, nodes, False,
                "image change")

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

    def validate_cp(self, task, requester, image_or_node_label, src, dst):
        return validate_cp(task, image_or_node_label, self, requester, src, dst)

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

    def shell_autocomplete(self, task, requester, username, argv, debug=False):
        return shell_autocomplete(self, task, requester, username, argv, debug=debug)

    def get_client_install_wheels(self):
        p = Path(__file__)
        while p.name != "walt":
            p = p.parent
        dist_packages = p.parent
        wheels = {}
        for record_file in dist_packages.glob("walt_*.dist-info/RECORD"):
            for component in ("common", "doc", "client", "client_g5k"):
                if not record_file.parent.name.startswith(f"walt_{component}-"):
                    continue
                whl_name, whl_content = self.generate_whl(
                        dist_packages, component, record_file)
                wheels[whl_name] = whl_content
        return wheels

    def generate_whl(self, dist_packages, component, record_file):
        versioned_component = f"walt_{component}-{__version__}"
        whl_name = f"{versioned_component}-py3-none-any.whl"
        record_file = dist_packages / f"{versioned_component}.dist-info/RECORD"
        whl_file = io.BytesIO()  # in-memory file
        with ZipFile(whl_file, 'w') as myzip:
            filtered_record = ""
            for line in record_file.read_text().splitlines():
                if line.startswith(".."):
                    continue
                if "__pycache__" in line:
                    continue
                if "direct_url.json" in line:
                    continue
                if "INSTALLER," in line:
                    continue
                if "REQUESTED," in line:
                    continue
                archive_path = line.split(",", maxsplit=1)[0]
                file_path = dist_packages / archive_path
                if file_path.name == "RECORD":
                    record_archive_path = archive_path
                else:
                    myzip.write(str(file_path), arcname=archive_path)
                filtered_record += f"{archive_path},,\n"
            myzip.writestr(record_archive_path, filtered_record)
        whl_file.seek(0)  # return to head of file
        whl_content = whl_file.read()
        whl_file.close()
        return whl_name, whl_content
