import os
import random

from walt.common.tcp import Requests
from walt.server.const import SSH_NODE_COMMAND
from walt.server.mount.setup import script_path
from walt.server.processes.main.parallel import ParallelProcessSocketListener
from walt.server.processes.main.workflow import Workflow

TYPE_CLIENT = 0
TYPE_IMAGE_OR_NODE = 1
TYPE_BOOTED_IMAGE = 2
RESPONSE_BAD = {"status": "FAILED"}

HELP_INVALID = dict(
    node="""\
Usage:
$ walt node cp <local_file_path> <node>:<file_path>
or
$ walt node cp <node>:<file_path> <local_file_path>
or
$ walt node cp <node>:<file_path> booted-image

Regular files as well as directories are accepted.
The 3rd form (with keyword 'booted-image') allows\
 to transfer files directly from the selected node
to the image it has booted. It is a shortcut to using\
 'walt node cp' and 'walt image cp' in sequence.

""",
    image="""\
Usage:
$ walt image cp <local_file_path> <image>:<file_path>
or
$ walt image cp <image>:<file_path> <local_file_path>

Regular files as well as directories are accepted.
""",
)

NODE_TFTP_ROOT = "/var/lib/walt/nodes/%(node_id)s/tftp"


class ClientFilesystemWorkflow:
    def __init__(self, filesystem):
        self._filesystem = filesystem

    def wf_get_file_type(self, wf, path, **env):
        ftype = self._filesystem.get_file_type(path)
        wf.update_env(ftype=ftype)
        wf.next()

    def wf_get_completions(self, wf, partial_path, **env):
        completions = self._filesystem.get_completions(partial_path)
        wf.update_env(remote_completions=completions)
        wf.next()


def get_random_suffix():
    return "".join(random.choice("0123456789ABCDEF") for i in range(8))


def _wf_analyse_file_types(wf, task, requester, operand_types, info,
        src_path, src_type, dst_path, dst_type, dst_parent_type=None, **kwargs):
    dst_dir = None
    if dst_type is None:
        # we might be in this case:
        # $ walt node cp <path> <node>:<existing_dir>/<new_entry>
        # so let's verify <existing_dir>.
        if dst_parent_type == "d":
            dst_type = "d"
            dst_name = os.path.basename(dst_path)
            dst_dir = os.path.dirname(dst_path)
    for ftype, path in [(src_type, src_path), (dst_type, dst_path)]:
        if ftype is None:
            requester.stderr.write("No such file or directory: %s\n" % path)
            task.return_result(RESPONSE_BAD)
            wf.interrupt()
            return
    if dst_type == "f":
        if src_type == "d":
            requester.stderr.write(
                "Invalid request. "
                + "Overwriting regular file %s with directory %s is not allowed.\n"
                % (dst_path, src_path)
            )
            task.return_result(RESPONSE_BAD)
            wf.interrupt()
            return
        # overwriting a file
        dst_type = "d"
        dst_name = os.path.basename(dst_path)
        dst_dir = os.path.dirname(dst_path)
    elif operand_types[1] == TYPE_BOOTED_IMAGE:
        # walt node cp <node>:/<existing_dir> booted-image
        # dir content should be merged into <existing_dir> in booted image
        dst_name = os.path.basename(dst_path)
        dst_dir = os.path.dirname(dst_path)
    elif dst_dir is None:
        if os.path.basename(src_path) == ".":
            # walt node cp '.' <node>:/<existing_dir>
            # dir content should be merged into <existing_dir>
            dst_name = os.path.basename(dst_path)
            dst_dir = os.path.dirname(dst_path)
        else:
            # walt node cp <path> <node>:/<existing_dir>
            # we have to keep the source name
            dst_name = os.path.basename(src_path)
            dst_dir = dst_path
    # all seems fine
    info.update(
        valid=True,
        dst_dir=dst_dir,
        dst_name=dst_name,
        src_path=src_path
    )
    task.return_result(info)
    wf.next()


def get_manager(server, image_or_node_label):
    if image_or_node_label == "node":
        return server.nodes
    else:
        return server.images


def validate_cp(task, image_or_node_label, server, requester, src, dst):
    invalid = False
    operand_types = []
    filesystems = []
    paths = []
    needs_confirm = False
    info = {}
    node_fs = None
    for index, operand in enumerate([src, dst]):
        parts = operand.rsplit(":", 1)  # caution, we may have <image>:<tag>:<path>
        if operand == "booted-image" or len(parts) > 1:
            if operand == "booted-image":
                operand_type = TYPE_BOOTED_IMAGE
                if image_or_node_label == "image":
                    requester.stderr.write(
                        "Keyword 'booted-image' is only available with command"
                        " 'walt node cp'.\n"
                    )
                    return RESPONSE_BAD
                elif index == 0:
                    requester.stderr.write(
                        "Keyword 'booted-image' can only be used as destination,"
                        " not source.\n"
                    )
                    return RESPONSE_BAD
                elif operand_types[0] != TYPE_IMAGE_OR_NODE:
                    invalid = True
                    break
                image_tag_or_node, path = "booted-image", paths[0]
                manager = server.images
            else:
                operand_type = TYPE_IMAGE_OR_NODE
                image_tag_or_node, path = parts
                manager = get_manager(server, image_or_node_label)
            status = manager.validate_cp_entity(
                requester, image_tag_or_node, index, **info
            )
            if status == "FAILED":
                return RESPONSE_BAD
            elif status == "NEEDS_CONFIRM":
                needs_confirm = True
            filesystem = manager.get_cp_entity_filesystem(
                requester, image_tag_or_node, **info
            )
            if image_or_node_label == "node":
                node_fs = filesystem
            info.update(
                **manager.get_cp_entity_attrs(requester, image_tag_or_node, **info)
            )
            filesystems.append(filesystem)
            paths.append(path.rstrip("/"))
        else:
            operand_type = TYPE_CLIENT
            filesystems.append(ClientFilesystemWorkflow(requester.filesystem))
            paths.append(operand.rstrip("/"))
            info.update(client_operand_index=index)
        operand_types.append(operand_type)
    if not invalid:
        if tuple(operand_types) not in (
            (TYPE_CLIENT, TYPE_IMAGE_OR_NODE),
            (TYPE_IMAGE_OR_NODE, TYPE_CLIENT),
            (TYPE_IMAGE_OR_NODE, TYPE_BOOTED_IMAGE),
        ):
            invalid = True
    if invalid:
        requester.stderr.write(HELP_INVALID[image_or_node_label])
        return RESPONSE_BAD
    src_fs, dst_fs = filesystems
    src_path, dst_path = [
        path if path.startswith("/") else "./" + path for path in paths
    ]
    info.update(status=("NEEDS_CONFIRM" if needs_confirm else "OK"))
    task.set_async()
    steps = []
    if node_fs is not None:
        steps += [node_fs.wf_ping, _wf_after_fs_ping]
    steps += [
       _wf_get_src_type,
       _wf_get_dst_type,
       _wf_analyse_file_types
    ]
    wf = Workflow(steps,
                  operand_types=operand_types,
                  src_fs=src_fs,
                  dst_fs=dst_fs,
                  src_path=src_path,
                  dst_path=dst_path,
                  task=task,
                  requester=requester,
                  info=info)
    wf.run()


def _wf_after_fs_ping(wf, task, requester, alive, **env):
    if alive:
        wf.next()
    else:
        requester.stderr.write("Could not reach this node. Try again later.\n")
        wf.interrupt()
        task.return_result({"status": "FAILED"})


def _wf_get_src_type(wf, src_fs, src_path, **env):
    wf.update_env(path=src_path)
    wf.insert_steps([src_fs.wf_get_file_type, _wf_save_src_type])
    wf.next()


def _wf_save_src_type(wf, ftype, **env):
    wf.update_env(src_type=ftype)
    wf.next()


def _wf_get_dst_type(wf, dst_fs, dst_path, **env):
    wf.update_env(path=dst_path)
    wf.insert_steps([dst_fs.wf_get_file_type, _wf_analyse_dst_type])
    wf.next()


def _wf_analyse_dst_type(wf, dst_fs, dst_path, ftype, **env):
    wf.update_env(dst_type=ftype)
    if ftype is not None:
        wf.next()
    else:
        # no file at dst_path
        # maybe dst_path specifies a new name for the destination file,
        # so let's verify that the parent directory exists.
        parent_path = os.path.dirname(dst_path)
        wf.update_env(path=parent_path)
        wf.insert_steps([dst_fs.wf_get_file_type, _wf_save_dst_parent_type])
        wf.next()


def _wf_save_dst_parent_type(wf, ftype, **env):
    wf.update_env(dst_parent_type=ftype)
    wf.next()


def docker_wrap_cmd(cmd, input_needed=False):
    input_opt = "-i" if input_needed else ""
    walt_tar_send = script_path("walt-tar-send")
    return f"""\
        podman run --log-driver=none -q {input_opt} \
        --name %(container_name)s -w /root \
        -v {walt_tar_send}:/bin/_walt_internal_/walt-tar-send \
        --entrypoint /bin/sh %(image_fullname)s -c "{cmd}; sync; sync" """


def ssh_wrap_cmd(cmd):
    return SSH_NODE_COMMAND + ' root@%(node_ip)s "' + cmd + '"'


TarSendCommand = """\
        /bin/_walt_internal_/walt-tar-send %(src_path)s %(dst_name)s \
        """


def get_absolute_path(path):
    if not path.startswith("/"):
        # relative path, turn to absolute.
        # all transfers use the root user,
        # so let's prefix with the home of root.
        return "/root/" + path
    return path


TarReceiveCommand = """\
        cd %(dst_dir)s && tar x"""


class ImageTarSender(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FROM_IMAGE

    def get_command(self, src_path, **params):
        src_path = get_absolute_path(src_path)
        return docker_wrap_cmd(TarSendCommand) % dict(
            tmp_name="." + get_random_suffix(), src_path=src_path, **params
        )


class ImageTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_TO_IMAGE

    def get_command(self, **params):
        return docker_wrap_cmd(TarReceiveCommand, input_needed=True) % params


class NodeTarSender(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FROM_NODE

    def get_command(self, src_path, **params):
        src_path = get_absolute_path(src_path)
        return ssh_wrap_cmd(TarSendCommand) % dict(
            tmp_name="." + get_random_suffix(), src_path=src_path, **params
        )


class NodeTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_TO_NODE

    def get_command(self, **params):
        return ssh_wrap_cmd(TarReceiveCommand) % params


IMAGE_BUILD_TAR_RECEIVER_COMMAND = """\
walt-annotate-cmd --mode pickle4 \
    walt-image-build-helper --from-stdin %(username)s %(image_fullname)s"""


class ImageBuildTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FOR_IMAGE_BUILD

    def get_command(self, **params):
        return IMAGE_BUILD_TAR_RECEIVER_COMMAND % params


class NodeFakeTFTPGet(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_FAKE_TFTP_GET

    def prepare(self, node_mac=None, node_ip=None, **params):
        if node_mac is not None:
            params["node_id"] = node_mac
        elif node_ip is not None:
            params["node_id"] = node_ip
        else:
            self.send_client("NO MAC OR IP SPECIFIED\n")
            return False
        full_path = (NODE_TFTP_ROOT + "%(path)s") % params
        if os.path.exists(full_path):
            self.send_client("OK\n")
            # send file length
            # (client will be able to close connection immediately after
            # the transfer, this is faster than detecting the end of the
            # 'cat' command)
            self.send_client(str(os.stat(full_path).st_size) + "\n")
            # save full_path for get_command() below
            self.params["full_path"] = full_path
            return True
        else:
            self.send_client("NO SUCH FILE\n")
            return False

    def get_command(self, **params):
        return 'cat "%(full_path)s"' % params


class VPNNodeImageDump(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_VPN_NODE_IMAGE

    def prepare(self, **params):
        if "model" not in params or "entrypoint" not in params:
            self.send_client("ERR Invalid request!\n")
            return False
        if params["model"] != "rpi-3-b-plus":
            self.send_client(
                "ERR Only rpi-3-b-plus boards can be used as a WalT node.\n"
            )
            return False
        self.send_client("MSG Generating image... Please be patient.\n")
        self.send_client("START\n")
        return True

    def get_command(self, **params):
        return (
            "podman run --log-driver=none -q --rm "
            "docker.io/waltplatform/rpi3bp-vpn-sd-dump"
            ' "%(entrypoint)s"' % params
        )


class TransferManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [
            ImageTarSender,
            ImageTarReceiver,
            NodeTarSender,
            NodeTarReceiver,
            ImageBuildTarReceiver,
            NodeFakeTFTPGet,
            VPNNodeImageDump,
        ]:
            tcp_server.register_listener_class(
                req_id=cls.REQ_ID, cls=cls, ev_loop=ev_loop
            )


def format_node_to_booted_image_transfer_cmd(src_path, **params):
    src_path = get_absolute_path(src_path)
    node_send_cmd = ssh_wrap_cmd(TarSendCommand) % dict(
        tmp_name="." + get_random_suffix(), src_path=src_path, **params
    )
    image_recv_cmd = docker_wrap_cmd(TarReceiveCommand, input_needed=True) % params
    return node_send_cmd + " | " + image_recv_cmd


def format_node_diff_dump_command(node_ip):
    return ssh_wrap_cmd("""/bin/_walt_internal_/walt-dump-diff-tar""") % dict(
            node_ip=node_ip)
