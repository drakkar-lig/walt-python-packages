#!/usr/bin/env python
import sys, os
from walt.client.config import conf
from walt.client.filesystem import Filesystem
from walt.common.api import api, api_expose_method, api_expose_attrs
from walt.common.apilink import ServerAPILink, BaseAPIService
from walt.common.tcp import client_sock_file
from walt.common.constants import WALT_SERVER_TCP_PORT
from walt.client.term import TTYSettings
from walt.client.update import check_update
from walt.client.startup import init_config

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
        self.stdin = ExposedStream(sys.stdin)
        self.stdout = ExposedStream(sys.stdout)
        self.stderr = ExposedStream(sys.stderr)
        self.filesystem = Filesystem()
        self.link = None
    @api_expose_method
    def get_username(self):
        return conf['username']
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

class InternalClientToServerLink(ServerAPILink):
    # optimization:
    # create service only once.
    # (this will allow to reuse an existing connection in the code of
    # ServerAPILink)
    service = WaltClientService()
    def __init__(self):
        InternalClientToServerLink.service.link = self
        ServerAPILink.__init__(self,
                conf['server'], 'CSAPI', InternalClientToServerLink.service)

class ClientToServerLink:
    num_calls = 0
    def __new__(cls):
        # on 1st call, check config, and once the config is OK
        # check if server version matches.
        if ClientToServerLink.num_calls == 0:
            init_config(InternalClientToServerLink)
        link = InternalClientToServerLink()
        if ClientToServerLink.num_calls == 0:
            with link as server:
                check_update(server)
        ClientToServerLink.num_calls += 1
        return link

def connect_to_tcp_server():
    # verify conf and connectivity to server through
    # its API endpoint
    with ClientToServerLink():
        pass
    # connect to TCP server endpoint
    return client_sock_file(conf['server'], WALT_SERVER_TCP_PORT)
