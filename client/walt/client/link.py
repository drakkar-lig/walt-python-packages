#!/usr/bin/env python
import os
import sys

from walt.client.config import conf, init_config
from walt.client.filesystem import Filesystem
from walt.client.plugins import get_hook
from walt.client.update import check_update
from walt.common.api import api, api_expose_attrs, api_expose_method
from walt.common.apilink import BaseAPIService, ServerAPILink
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.tcp import client_sock_file


@api
class ExposedStream(object):
    def __init__(self, stream):
        self.stream = stream

    @api_expose_method
    def fileno(self):
        return self.stream.fileno()

    @api_expose_method
    def readline(self, size=-1):
        return self.stream.readline(size)

    @api_expose_method
    def write(self, s):
        self.stream.write(s)

    @api_expose_method
    def flush(self):
        self.stream.flush()

    @api_expose_method
    def get_encoding(self):
        if hasattr(self.stream, "encoding"):
            return self.stream.encoding
        else:
            return None

    @api_expose_method
    def isatty(self):
        return os.isatty(self.stream.fileno())


# most of the functionality is provided at the server,
# of course.
# but the client also exposes a few objects / features
# in the following class.
@api
class WaltClientService(BaseAPIService):
    @api_expose_attrs("stdin", "stdout", "stderr", "filesystem")
    def __init__(self):
        super().__init__()
        self.stdin = ExposedStream(sys.stdin)
        self.stdout = ExposedStream(sys.stdout)
        self.stderr = ExposedStream(sys.stderr)
        self.filesystem = Filesystem()
        self.link = None

    @api_expose_method
    def get_username(self):
        return conf.walt.username

    @api_expose_method
    def get_win_size(self):
        from walt.common.term import TTYSettings
        tty = TTYSettings()
        return {"cols": tty.cols, "rows": tty.rows}

    @api_expose_method
    def set_busy_label(self, busy_label):
        self.link.set_busy_label(busy_label)

    @api_expose_method
    def set_default_busy_label(self):
        self.link.set_default_busy_label()

    @api_expose_method
    def has_hook(self, hook_name):
        return get_hook(hook_name) is not None

    @api_expose_method
    def get_hard_reboot_method_name(self):
        return get_hook("client_hard_reboot").method_name

    @api_expose_method
    def hard_reboot_nodes(self, node_macs):
        return get_hook("client_hard_reboot").reboot(node_macs)

    @api_expose_method
    def get_registry_encrypted_credentials(self, registry_label, server_pub_key):
        reg_conf = getattr(conf.registries, registry_label)
        from walt.client.auth import get_encrypted_credentials
        return get_encrypted_credentials(
            server_pub_key, reg_conf.username, reg_conf.password
        )

    @api_expose_method
    def get_registry_username(self, registry_label):
        reg_conf = getattr(conf.registries, registry_label)
        return reg_conf.username


class InternalClientToServerLink(ServerAPILink):
    # optimization:
    # create service only once.
    # (this will allow to reuse an existing connection in the code of
    # ServerAPILink)
    service = WaltClientService()

    def __init__(self, busy_indicator):
        InternalClientToServerLink.service.link = self
        ServerAPILink.__init__(
            self,
            conf.walt.server,
            "CSAPI",
            InternalClientToServerLink.service,
            busy_indicator,
        )


class ClientToServerLink:
    init_config_done = False
    full_init_done = False

    def __new__(cls, do_checks=True, busy_indicator=None):
        def get_link():
            return InternalClientToServerLink(busy_indicator)

        # on 1st call:
        # 1) check config, and once the config is OK
        # 2) check if server version matches
        if not ClientToServerLink.init_config_done:
            init_config(get_link)
            ClientToServerLink.init_config_done = True
        link = get_link()
        if not ClientToServerLink.full_init_done:
            if do_checks:
                with link as server:
                    check_update(server)
            ClientToServerLink.full_init_done = True
        return link


def connect_to_tcp_server():
    # verify conf and connectivity to server through
    # its API endpoint
    with ClientToServerLink():
        pass
    # connect to TCP server endpoint
    return client_sock_file(conf.walt.server, WALT_SERVER_TCP_PORT)
