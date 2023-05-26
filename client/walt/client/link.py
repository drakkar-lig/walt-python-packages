#!/usr/bin/env python
import sys, os
from walt.client.config import conf, init_config
from walt.client.filesystem import Filesystem
from walt.common.api import api, api_expose_method, api_expose_attrs
from walt.common.apilink import ServerAPILink, BaseAPIService
from walt.common.tcp import client_sock_file
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.common.term import TTYSettings
from walt.client.update import check_update
from walt.client.plugins import get_hook
from walt.client.auth import get_encrypted_credentials

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
        if hasattr(self.stream, 'encoding'):
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
    @api_expose_attrs('stdin','stdout','stderr','filesystem')
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
        tty = TTYSettings()
        return { 'cols': tty.cols, 'rows': tty.rows }
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
        return get_hook('client_hard_reboot').method_name
    @api_expose_method
    def hard_reboot_nodes(self, node_macs):
        return get_hook('client_hard_reboot').reboot(node_macs)
    @api_expose_method
    def get_registry_encrypted_credentials(self, registry_label, server_pub_key):
        reg_conf = getattr(conf.registries, registry_label)
        return get_encrypted_credentials(server_pub_key,
                                         reg_conf.username, reg_conf.password)
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
        ServerAPILink.__init__(self,
                conf.walt.server, 'CSAPI',
                InternalClientToServerLink.service, busy_indicator)

class ClientToServerLink:
    num_calls = 0
    def __new__(cls, do_checks=True, busy_indicator=None):
        def get_link():
            return InternalClientToServerLink(busy_indicator)
        # on 1st call:
        # 1) check config, and once the config is OK
        # 2) check if server version matches
        # 3) execute connection hook if any
        # 4) set faster pickle4 mode
        if ClientToServerLink.num_calls == 0:
            init_config(get_link)
            return get_link()
        link = get_link()
        if not do_checks:
            return link
        if ClientToServerLink.num_calls == 0:
            with link as server:
                check_update(server)
                connection_hook = get_hook('connection_hook')
                if connection_hook is not None:
                    connection_hook(link, server)
                link.set_mode('pickle4')
        ClientToServerLink.num_calls += 1
        return link

def connect_to_tcp_server():
    # verify conf and connectivity to server through
    # its API endpoint
    with ClientToServerLink():
        pass
    # connect to TCP server endpoint
    return client_sock_file(conf.walt.server, WALT_SERVER_TCP_PORT)
