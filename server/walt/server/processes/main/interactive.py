#!/usr/bin/env python
from walt.common.tcp import Requests
from walt.server.const import SSH_COMMAND
from walt.server.processes.main.parallel import ParallelProcessSocketListener

# when running walt image shell, run bash if available, sh otherwise.
DOCKER_SH_PATTERN = """\
walt-image-shell-helper "%(image_fullname)s" "%(container_name)s" """


class PromptSocketListener(ParallelProcessSocketListener):
    def update_params(self):
        if "env" not in self.params:
            self.params["env"] = {}
        if "TERM" not in self.params["env"]:
            self.params["env"]["TERM"] = "xterm"


class SQLPromptSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_SQL_PROMPT

    def get_command(self, **params):
        return "psql walt"


class DockerPromptSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_DOCKER_PROMPT

    def get_command(self, **params):
        return DOCKER_SH_PATTERN % dict(
            container_name=params["container_name"],
            image_fullname=params["image_fullname"],
        )


class NodeCmdSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_NODE_CMD

    def get_command(self, node_ip, cmdargs, ssh_tty, **kwargs):
        cmd = " ".join(cmdargs)
        if cmd == "":
            quoted_cmd = ""
        else:
            quoted_cmd = "'" + "'\"'\"'".join(cmd.split("'")) + "'"
        ssh_cmd = SSH_COMMAND
        if ssh_tty:
            ssh_cmd += " -t"
        return "%(ssh)s root@%(ip)s %(cmd)s" % dict(
            ssh=ssh_cmd, ip=node_ip, cmd=quoted_cmd
        )


class DevicePingSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_DEVICE_PING

    def get_command(self, **params):
        return "ping %s" % params["device_ip"]


class DeviceShellSocketListener(PromptSocketListener):
    REQ_ID = Requests.REQ_DEVICE_SHELL

    def get_command(self, **params):
        user = params["user"]
        ip = params["device_ip"]
        return f"ssh -o PreferredAuthentications=password {user}@{ip}"


class InteractionManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [
            SQLPromptSocketListener,
            DockerPromptSocketListener,
            NodeCmdSocketListener,
            DevicePingSocketListener,
            DeviceShellSocketListener,
        ]:
            tcp_server.register_listener_class(
                req_id=cls.REQ_ID, cls=cls, ev_loop=ev_loop
            )
