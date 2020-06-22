
from walt.common.tcp import Requests
from walt.server.threads.main.parallel import ParallelProcessSocketListener
from walt.server.const import SSH_COMMAND
import os, random

TYPE_CLIENT = 0
TYPE_IMAGE_OR_NODE = 1
TYPE_BOOTED_IMAGE = 2

HELP_INVALID = dict(
    node = """\
Usage:
$ walt node cp <local_file_path> <node>:<file_path>
or
$ walt node cp <node>:<file_path> <local_file_path>
or
$ walt node cp <node>:<file_path> booted-image

Regular files as well as directories are accepted.
The 3rd form (with keyword 'booted-image') allows to transfer files directly from the selected node
to the image it has booted. It is a shortcut to using 'walt node cp' and 'walt image cp' in sequence.

""",
    image = """\
Usage:
$ walt image cp <local_file_path> <image>:<file_path>
or
$ walt image cp <image>:<file_path> <local_file_path>

Regular files as well as directories are accepted.
""")

NODE_TFTP_ROOT = "/var/lib/walt/nodes/%(node_mac)s/tftp"

def get_random_suffix():
    return ''.join(random.choice('0123456789ABCDEF') for i in range(8))

def analyse_file_types(requester, operand_types, src_path, src_fs, dst_path, dst_fs, **kwargs):
    bad = dict(valid = False)
    dst_dir = None
    src_type = src_fs.get_file_type(src_path)
    dst_type = dst_fs.get_file_type(dst_path)
    if dst_type is None:
        # maybe this is just the target filename, let's verify that the parent
        # directory exists
        parent_path = os.path.dirname(dst_path)
        if dst_fs.get_file_type(parent_path) == 'd':
            # walt node cp <path> <node>:<existing_dir>/<new_entry>
            dst_type = 'd'
            dst_name = os.path.basename(dst_path)
            dst_dir = parent_path
    for ftype, path in [(src_type, src_path), (dst_type, dst_path)]:
        if ftype is None:
            requester.stderr.write('No such file or directory: %s\n' % path)
            return bad
    if dst_type == 'f':
        if src_type == 'd':
            requester.stderr.write(
                "Invalid request. " + \
                "Overwriting regular file %s with directory %s is not allowed.\n" % \
                    (dst_path, src_path))
            return bad
        # overwriting a file
        dst_type = 'd'
        dst_name = os.path.basename(dst_path)
        dst_dir = os.path.dirname(dst_path)
    elif operand_types[1] == TYPE_BOOTED_IMAGE:
        # walt node cp <node>:/<existing_dir> booted-image
        # dir content should be merged into <existing_dir> in booted image
        dst_name = os.path.basename(dst_path)
        dst_dir = os.path.dirname(dst_path)
    elif dst_dir is None:
        if os.path.basename(src_path) is '.':
            # walt node cp '.' <node>:/<existing_dir>
            # dir content should be merged into <existing_dir>
            dst_name = os.path.basename(dst_path)
            dst_dir = os.path.dirname(dst_path)
        else:
            # walt node cp <path> <node>:/<existing_dir>
            # we have to keep the source name
            dst_name = os.path.basename(src_path)
            dst_dir = dst_path
    kwargs.update(
        valid = True,
        dst_dir = dst_dir,
        dst_name = dst_name
    )
    return kwargs

def get_manager(server, image_or_node_label):
    if image_or_node_label == 'node':
        return server.nodes
    else:
        return server.images

def validate_cp(image_or_node_label, server,
                requester, src, dst):
    invalid = False
    operand_types = []
    client_operand_index = -1
    filesystems = []
    paths = []
    needs_confirm = False
    info = {}
    for index, operand in enumerate([src, dst]):
        parts = operand.rsplit(':', 1)  # caution, we may have <image>:<tag>:<path>
        if operand == 'booted-image' or len(parts) > 1:
            if operand == 'booted-image':
                operand_type = TYPE_BOOTED_IMAGE
                if image_or_node_label == 'image':
                    requester.stderr.write(\
                        "Keyword 'booted-image' is only available with command 'walt node cp'.\n")
                    return { 'status': 'FAILED' }
                elif index == 0:
                    requester.stderr.write(\
                        "Keyword 'booted-image' can only be used as destination, not source.\n")
                    return { 'status': 'FAILED' }
                elif operand_types[0] != TYPE_IMAGE_OR_NODE:
                    invalid = True
                    break
                image_tag_or_node, path = 'booted-image', paths[0]
                manager = server.images
            else:
                operand_type = TYPE_IMAGE_OR_NODE
                image_tag_or_node, path = parts
                manager = get_manager(server, image_or_node_label)
            status = manager.validate_cp_entity(requester, image_tag_or_node, index, **info)
            if status == 'FAILED':
                return { 'status': 'FAILED' }
            elif status == 'NEEDS_CONFIRM':
                needs_confirm = True
            filesystem = manager.get_cp_entity_filesystem(
                                    requester, image_tag_or_node, **info)
            if not filesystem.ping():
                requester.stderr.write(\
                    "Could not reach %s. Try again later.\n" % image_tag_or_node)
                return { 'status': 'FAILED' }
            info.update(
                **manager.get_cp_entity_attrs(requester, image_tag_or_node, **info))
            filesystems.append(filesystem)
            paths.append(path.rstrip('/'))
        else:
            operand_type = TYPE_CLIENT
            filesystems.append(requester.filesystem)
            paths.append(operand.rstrip('/'))
            client_operand_index = index
        operand_types.append(operand_type)
    if not invalid:
        if tuple(operand_types) not in (
                (TYPE_CLIENT, TYPE_IMAGE_OR_NODE),
                (TYPE_IMAGE_OR_NODE, TYPE_CLIENT),
                (TYPE_IMAGE_OR_NODE, TYPE_BOOTED_IMAGE)):
            invalid = True
    if invalid:
        requester.stderr.write(HELP_INVALID[image_or_node_label])
        return { 'status': 'FAILED' }
    src_fs, dst_fs = filesystems
    src_path, dst_path = [
            path if path.startswith('/') else './' + path
            for path in paths ]
    info.update(**analyse_file_types(  requester, operand_types,
                                src_path, src_fs,
                                dst_path, dst_fs))
    if info.pop('valid') == False:
        return { 'status': 'FAILED' }
    # all seems fine
    info.update(
        status = ('NEEDS_CONFIRM' if needs_confirm else 'OK'),
        src_path = src_path,
        client_operand_index = client_operand_index
    )
    print(info)
    return info

def docker_wrap_cmd(cmd, input_needed = False):
    input_opt = '-i' if input_needed else ''
    return '''\
        podman run %(input_opt)s --name %%(container_name)s \
        --entrypoint /bin/sh %%(image_fullname)s -c "%(cmd)s; sync; sync"
    ''' % dict(cmd = cmd, input_opt = input_opt)

def ssh_wrap_cmd(cmd):
    return SSH_COMMAND + ' root@%(node_ip)s "' + cmd + '"'

TarSendCommand='''\
        mkdir -p /tmp/%(tmp_name)s && cd /tmp/%(tmp_name)s && \
        ln -s %(src_path)s %(dst_name)s && \
        tar c -h %(dst_name)s && cd / && rm -rf /tmp/%(tmp_name)s '''

TarReceiveCommand='''\
        cd %(dst_dir)s && tar x'''

class ImageTarSender(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FROM_IMAGE
    def get_command(self, **params):
        return docker_wrap_cmd(TarSendCommand) % dict(
            tmp_name = '.' + get_random_suffix(),
            **params
        )

class ImageTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_TO_IMAGE
    def get_command(self, **params):
        return docker_wrap_cmd(\
                TarReceiveCommand, input_needed = True) % params

class NodeTarSender(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FROM_NODE
    def get_command(self, **params):
        return ssh_wrap_cmd(TarSendCommand) % dict(
            tmp_name = '.' + get_random_suffix(),
            **params
        )

class NodeTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_TO_NODE
    def get_command(self, **params):
        return ssh_wrap_cmd(TarReceiveCommand) % params

class NodeFakeTFTPGet(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_FAKE_TFTP_GET
    def prepare(self, **params):
        full_path = (NODE_TFTP_ROOT + '%(path)s') % params
        if os.path.exists(full_path):
            self.send_client('OK\n')
            # send file length
            # (client will be able to close connection immediately after
            # the transfer, this is faster than detecting the end of the
            # 'cat' command)
            self.send_client(str(os.stat(full_path).st_size) + '\n')
            # save full_path for get_command() below
            self.params['full_path'] = full_path
            return True
        else:
            self.send_client('NO SUCH FILE\n')
            return False
    def get_command(self, **params):
        return 'cat "%(full_path)s"' % params

class VPNNodeImageDump(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_VPN_NODE_IMAGE
    def prepare(self, **params):
        if 'model' not in params or 'entrypoint' not in params:
            self.send_client('ERR Invalid request!\n')
            return False
        if params['model'] != 'rpi-3-b-plus':
            self.send_client('ERR Only rpi-3-b-plus boards can be used as a WalT node.\n')
            return False
        self.send_client('MSG Generating image... Please be patient.\n')
        self.send_client('START\n')
        return True
    def get_command(self, **params):
        return 'podman run --rm waltplatform/rpi3bp-vpn-sd-dump "%(entrypoint)s"' % params

class TransferManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [    ImageTarSender,
                        ImageTarReceiver,
                        NodeTarSender,
                        NodeTarReceiver,
                        NodeFakeTFTPGet,
                        VPNNodeImageDump ]:
            tcp_server.register_listener_class(
                    req_id = cls.REQ_ID,
                    cls = cls,
                    ev_loop = ev_loop)

def format_node_to_booted_image_transfer_cmd(**params):
    node_send_cmd = ssh_wrap_cmd(TarSendCommand) % dict(
        tmp_name = '.' + get_random_suffix(),
        **params
    )
    image_recv_cmd = docker_wrap_cmd(
            TarReceiveCommand, input_needed = True) % params
    return node_send_cmd + ' | ' + image_recv_cmd
