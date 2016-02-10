
from walt.common.tcp import Requests
from walt.server.parallel import ParallelProcessSocketListener
from walt.server.const import SSH_COMMAND
import os

TYPE_CLIENT = 0
TYPE_IMAGE = 1

HELP_INVALID = """\
Usage:
$ walt $(image_or_node_label) cp <local_file_path> <$(image_or_node_label)>:<file_path>
or
$ walt $(image_or_node_label) cp <$(image_or_node_label)>:<file_path> <local_file_path>

Regular files as well as directories are accepted.
"""

def analyse_file_types(requester, image_tag_or_node, src_path, src_fs, dst_path, dst_fs, **kwargs):
    bad = dict(valid = False)
    dst_dir = None
    src_type = src_fs.get_file_type(src_path)
    dst_type = dst_fs.get_file_type(dst_path)
    if dst_type is None:
        # maybe this is just the target filename, let's verify that the parent
        # directory exists
        parent_path = os.path.dirname(dst_path)
        if dst_fs.get_file_type(parent_path) == 'd':
            # ok
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
    elif dst_dir is None:
        # copying to a directory, keeping the source name
        dst_name = os.path.basename(src_path)
        dst_dir = dst_path
    kwargs.update(
        valid = True,
        dst_dir = dst_dir,
        dst_name = dst_name
    )
    return kwargs

def validate_cp(image_or_node_label, caller,
                requester, src, dst):
    invalid = False
    operands = []
    operand_index_per_type = {}
    filesystems = []
    paths = []
    image_tag = None
    for index, operand in enumerate([src, dst]):
        parts = operand.split(':')
        operand_type = len(parts)-1
        if operand_type > 1:
            invalid = True
            break
        operands.append(operand)
        operand_index_per_type[operand_type] = index
        if operand_type == TYPE_CLIENT:
            filesystems.append(requester.filesystem)
            paths.append(operand.rstrip('/'))
        else:
            image_tag_or_node, path = parts
            if not caller.validate_cp_entity(requester, image_tag_or_node):
                return
            filesystem = caller.get_cp_entity_filesystem(
                                    requester, image_tag_or_node)
            if not filesystem.ping():
                requester.stderr.write(\
                    "Could not reach %s. Try again later.\n" % image_tag_or_node)
                return
            filesystems.append(filesystem)
            paths.append(path.rstrip('/'))
    if len(operand_index_per_type) != 2:
        invalid = True
    if invalid:
        requester.stderr.write(HELP_INVALID % dict(
            image_or_node_label = image_or_node_label
        ))
        return
    src_fs, dst_fs = filesystems
    src_path, dst_path = [
            path if path.startswith('/') else './' + path
            for path in paths ]
    info = analyse_file_types(  requester, image_tag_or_node,
                                src_path, src_fs,
                                dst_path, dst_fs)
    if info.pop('valid') == False:
        return
    # all seems fine
    client_operand_index = operand_index_per_type[TYPE_CLIENT]
    info.update(
        src_dir = os.path.dirname(src_path),
        src_name = os.path.basename(src_path),
        client_operand_index = client_operand_index,
        **caller.get_cp_entity_attrs(requester, image_tag_or_node)
    )
    # return an immutable object
    return tuple(info.items())

def docker_wrap_cmd(cmd):
    return '''\
        docker run -i --name %%(container_name)s --entrypoint /bin/sh \
        %%(image_fullname)s -c "%s; sync; sync"
    ''' % cmd

def ssh_wrap_cmd(cmd):
    return SSH_COMMAND + ' root@%(node_ip)s "' + cmd + '"'

TarSendCommand='''\
        tar c -C %(src_dir)s %(src_name)s \
        --transform 's/^[^\/]*/%(dst_name)s/' '''

TarReceiveCommand='''\
        tar x -C %(dst_dir)s'''

class ImageTarSender(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FROM_IMAGE
    def get_command(self, **params):
        return docker_wrap_cmd(TarSendCommand) % params

class ImageTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_TO_IMAGE
    def get_command(self, **params):
        return docker_wrap_cmd(TarReceiveCommand) % params

class NodeTarSender(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FROM_NODE
    def get_command(self, **params):
        return ssh_wrap_cmd(TarSendCommand) % params

class NodeTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_TO_NODE
    def get_command(self, **params):
        return ssh_wrap_cmd(TarReceiveCommand) % params

class TransferManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [    ImageTarSender,
                        ImageTarReceiver,
                        NodeTarSender,
                        NodeTarReceiver ]:
            tcp_server.register_listener_class(
                    req_id = cls.REQ_ID,
                    cls = cls,
                    ev_loop = ev_loop)

