
from walt.common.tcp import Requests
from walt.server.parallel import ParallelProcessSocketListener

TarSendCommand='''\
docker run --name %(container_name)s --entrypoint tar \
        %(image_fullname)s \
        c -C %(src_dir)s %(src_name)s \
        --transform 's/^[^\/]*/%(dst_name)s/' '''

class DockerImageTarSender(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_FROM_IMAGE
    def get_command(self, **params):
        return TarSendCommand % params

TarReceiveCommand='''\
docker run -i --name %(container_name)s --entrypoint tar \
        %(image_fullname)s \
        x -C %(dst_dir)s'''

class DockerImageTarReceiver(ParallelProcessSocketListener):
    REQ_ID = Requests.REQ_TAR_TO_IMAGE
    def get_command(self, **params):
        return TarReceiveCommand % params

class TransferManager(object):
    def __init__(self, tcp_server, ev_loop):
        for cls in [    DockerImageTarSender,
                        DockerImageTarReceiver ]:
            tcp_server.register_listener_class(
                    req_id = cls.REQ_ID,
                    cls = cls,
                    ev_loop = ev_loop)

