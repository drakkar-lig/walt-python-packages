#!/usr/bin/env python
from walt.common.tcp import Requests
from walt.server.parallel import ParallelProcessSocketListener
from walt.server.const import SSH_COMMAND

INTERACTIVE_SSH_COMMAND = SSH_COMMAND + ' -tq'

class PromptSocketListener(ParallelProcessSocketListener):
    def update_params(self):
        self.params.update(
            env={'TERM':'xterm'},
            want_tty=True    # preferably start subprocess in a virtual terminal
        )

class SQLPromptSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_SQL_PROMPT
    def get_command(self, **params):
        return 'psql walt'

class DockerPromptSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_DOCKER_PROMPT
    def get_command(self, **params):
        return 'docker run -it --entrypoint %s -h %s --name %s %s' % \
                       ('/bin/bash', 'image-shell',
                        params['container_name'], params['image_fullname'])

class NodeCmdSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_NODE_CMD
    def get_command(self, node_ip, cmdargs, **kwargs):
        cmd = ' '.join(cmdargs)
        quoted_cmd = "'" + "'\"'\"'".join(cmd.split("'")) + "'"
        return '%(ssh)s root@%(ip)s %(cmd)s' % dict(
            ssh = INTERACTIVE_SSH_COMMAND,
            ip = node_ip,
            cmd = quoted_cmd
        )

class DevicePingSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_DEVICE_PING
    def get_command(self, **params):
        return 'ping %s' % params['device_ip']

class InteractionManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [    SQLPromptSocketListener,
                        DockerPromptSocketListener,
                        NodeCmdSocketListener,
                        DevicePingSocketListener ]:
            tcp_server.register_listener_class(
                    req_id = cls.REQ_ID,
                    cls = cls,
                    ev_loop = ev_loop)

