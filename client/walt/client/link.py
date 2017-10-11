#!/usr/bin/env python
import sys
from walt.client.config import conf
from walt.client.filesystem import Filesystem
from walt.common.api import api, api_expose_method, api_expose_attrs
from walt.common.apilink import ServerAPILink

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

# most of the functionality is provided at the server,
# of course.
# but the client also exposes a few objects / features
# in the following class.
@api
class WaltClientService(object):
    @api_expose_attrs('stdin','stdout','stderr','filesystem')
    def __init__(self):
        self.stdin = ExposedStream(sys.stdin)
        self.stdout = ExposedStream(sys.stdout)
        self.stderr = ExposedStream(sys.stderr)
        self.filesystem = Filesystem()
    @api_expose_method
    def get_username(self):
        return conf['username']

class ClientToServerLink(ServerAPILink):
    # optimization:
    # create service only once.
    # (this will allow to reuse an existing connection in the code of
    # ServerAPILink)
    service = WaltClientService()
    def __init__(self):
        ServerAPILink.__init__(self,
                conf['server'], 'CSAPI', ClientToServerLink.service)
