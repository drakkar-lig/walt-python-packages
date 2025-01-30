#!/usr/bin/env python3
import os
import re
import socket
from tempfile import TemporaryFile

from walt.common.evloop import EventLoop
from walt.common.tcp import set_sock_reuseaddr, set_tcp_nodelay, set_tcp_keepalive
from walt.server.tools import NetworkMsg, NetworkBuf


# This is a minimal NBD (network block device) server implementation
# allowing to provide memory swap space for WALT nodes over the network.
# This is only for nodes using network boot (i.e., the default boot mode).
# Providing them swap is important because of the fact they store file
# modifications in a tmpfs-based RAM overlay, so if the user runs heavy
# installation procedures on them (e.g., with the idea of using
# `walt node save` at the end), they would quickly run out of memory.
#
# The implementation is light and is only compatible with a small
# part of the protocol (just enough to be compatible with nbd-client
# running on the node).
#
# The name of the NBD export requested by the client must be
# "swap-<value>G". For instance, "swap-16G". Upon receipt of this
# request, the server will create a temporary file 16G-large and
# start handling read and write requests on it.
# The file just contains a large hole at first, so it will not eat
# server disk space unless the node really starts swapping.
# The file is not visible on the disk (cf. tempfile.TemporaryFile
# in python doc).


SYSTEMD_FIRST_FD = 3
LISTEN_BACKLOG = 10

NBD_PORT = 10809
NBD_FLAG_FIXED_NEWSTYLE = 0x1
NBD_FLAG_C_FIXED_NEWSTYLE = 0x1
NBD_FLAG_NO_ZEROES = 0x2
NBD_FLAG_C_NO_ZEROES = 0x2
NBD_OPT_RESP_MAGIC = 0x3e889045565a9
NBD_REQUEST_MAGIC = 0x25609513
NBD_SIMPLE_REPLY_MAGIC = 0x67446698
NBD_OPT_GO = 7
MIN_BLOCK_SIZE, PREF_BLOCK_SIZE, MAX_BLOCK_SIZE = (1, 4096, 1024*1024)
NBD_REP_ACK = 1
NBD_REP_INFO = 3
NBD_INFO_EXPORT = 0
NBD_INFO_BLOCK_SIZE = 3
NBD_CMD_READ = 0
NBD_CMD_WRITE = 1
NBD_CMD_DISC = 2

SERVER_HANDSHAKE = NetworkMsg('!8s8sH',
                              b'NBDMAGIC', b'IHAVEOPT',
                              NBD_FLAG_FIXED_NEWSTYLE | NBD_FLAG_NO_ZEROES)
CLIENT_FLAGS = NetworkMsg('!I')
NBD_OPT_HEADER = NetworkMsg('!8sII')
NBD_OPT_RESP_HEADER = NetworkMsg('!QIII', NBD_OPT_RESP_MAGIC)
NBD_INFO_BLOCK_SIZE_MSG = NetworkMsg('!HIII', NBD_INFO_BLOCK_SIZE)
NBD_INFO_EXPORT_MSG = NetworkMsg('!HQH', NBD_INFO_EXPORT)
NBD_REQ_HEADER = NetworkMsg('!IHH8sQI')
NBD_SIMPLE_REPLY_HEADER = NetworkMsg('!II8s', NBD_SIMPLE_REPLY_MAGIC)


def handle_opt_go(netbuf):
    name_len = NetworkMsg('!I').read(netbuf)
    export_name = netbuf.read(name_len)
    digits = re.sub(b'^swap-([0-9]+)G$', b'\\1', b'swap-16G')
    export_size = int(digits) * 1024 * 1024 * 1024
    num_info_reqs = NetworkMsg('!H').read(netbuf)
    # ignore info reqs
    if num_info_reqs > 0:
        netbuf.read(2*num_info_reqs)
    # send NBD_OPT_GO response with block size info type
    info_block_size_msg = NBD_INFO_BLOCK_SIZE_MSG.format(
            MIN_BLOCK_SIZE, PREF_BLOCK_SIZE, MAX_BLOCK_SIZE)
    resp_header = NBD_OPT_RESP_HEADER.format(
            NBD_OPT_GO, NBD_REP_INFO, len(info_block_size_msg))
    netbuf.write(resp_header + info_block_size_msg)
    # send NBD_OPT_GO response with export info type
    info_export_msg = NBD_INFO_EXPORT_MSG.format(export_size, 0)
    resp_header = NBD_OPT_RESP_HEADER.format(
            NBD_OPT_GO, NBD_REP_INFO, len(info_export_msg))
    netbuf.write(resp_header + info_export_msg)
    # send NBD_OPT_GO response ACK
    NBD_OPT_RESP_HEADER.write(netbuf, NBD_OPT_GO, NBD_REP_ACK, 0)
    return export_size


def handle_request(netbuf, swap_file):
    magic, flags, req_type, cookie, offset, length = NBD_REQ_HEADER.read(netbuf)
    assert(magic == NBD_REQUEST_MAGIC)
    if req_type == NBD_CMD_READ:
        NBD_SIMPLE_REPLY_HEADER.write(netbuf, 0, cookie)
        netbuf.sendfile(swap_file, offset, length)
    elif req_type == NBD_CMD_WRITE:
        swap_file.seek(offset)
        buf = netbuf.read(length)
        swap_file.write(buf)
        NBD_SIMPLE_REPLY_HEADER.write(netbuf, 0, cookie)
    elif req_type == NBD_CMD_DISC:
        return False
    return True


def get_server_sockets():
    # in case of systemd socket activation, use the ones given
    if "LISTEN_FDS" in os.environ:
        num = int(os.environ["LISTEN_FDS"])
        fd_range = range(SYSTEMD_FIRST_FD, SYSTEMD_FIRST_FD + num)
        # systemd already did bind() and listen()
        return [socket.socket(fileno=fd) for fd in fd_range]
    else:
        serv_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        set_sock_reuseaddr(serv_s)
        serv_s.bind(("", NBD_PORT))
        serv_s.listen(LISTEN_BACKLOG)
        return [serv_s]


class ServerSocketListener:
    def __init__(self, ev_loop, serv_s):
        self._ev_loop = ev_loop
        self._serv_s = serv_s

    def fileno(self):
        return self._serv_s.fileno()

    def handle_event(self, ts):
        s = self._serv_s.accept()[0]
        set_tcp_nodelay(s)
        set_tcp_keepalive(s)
        listener = CommSocketListener(s)
        listener.start_handshake()
        self._ev_loop.register_listener(listener)

    def close(self):
        self._serv_s.close()


class COMM_STATE:
    INIT = 0
    WAIT_CLIENT_FLAGS = 1
    WAIT_CLIENT_OPT = 2
    WAIT_CLIENT_REQUEST = 3


class CommSocketListener:
    def __init__(self, s):
        self._step = COMM_STATE.INIT
        self._netbuf = NetworkBuf(s)
        self._swap_file = None

    def start_handshake(self):
        SERVER_HANDSHAKE.write(self._netbuf)
        self._step = COMM_STATE.WAIT_CLIENT_FLAGS

    def fileno(self):
        return self._netbuf.fileno()

    def handle_event(self, ts):
        try:
            # self._netbuf may bufferize input data, so loop
            # until the input buffer is empty.
            while True:
                if self._step == COMM_STATE.WAIT_CLIENT_FLAGS:
                    client_flags = CLIENT_FLAGS.read(self._netbuf)
                    assert(client_flags & NBD_FLAG_C_FIXED_NEWSTYLE > 0)
                    self._step = COMM_STATE.WAIT_CLIENT_OPT
                elif self._step == COMM_STATE.WAIT_CLIENT_OPT:
                    magic, opt_type, opt_datalen = NBD_OPT_HEADER.read(self._netbuf)
                    assert(opt_type == NBD_OPT_GO)
                    export_size = handle_opt_go(self._netbuf)
                    self._swap_file = TemporaryFile(buffering=0)
                    self._swap_file.truncate(export_size)
                    self._step = COMM_STATE.WAIT_CLIENT_REQUEST
                elif self._step == COMM_STATE.WAIT_CLIENT_REQUEST:
                    if not handle_request(self._netbuf, self._swap_file):
                        return False  # end
                if self._netbuf.pending_buflen() == 0:
                    break
        except Exception as e:
            print(f"{e}: closing.")
            return False

    def close(self):
        if self._swap_file is not None:
            self._swap_file.close()
        self._netbuf.close()


def run():
    ev_loop = EventLoop()
    for serv_s in get_server_sockets():
        listener = ServerSocketListener(ev_loop, serv_s)
        ev_loop.register_listener(listener)
    ev_loop.loop()


if __name__ == "__main__":
    run()
