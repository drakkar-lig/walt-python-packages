import socket
import struct
from time import time

from walt.common.tcp import Requests


def get_rtt_us(sock):
    # tcp_info: 8 bytes header + uint32 fields; tcpi_rtt is the 16th uint32
    buf = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 1024)
    # see struct tcp_info in /usr/include/linux/tcp.h
    tcp_info = struct.unpack(
            "B"*8 + "I"*24 + "Q"*4 + "I"*6 +
            "Q"*4 + "I"*2 + "Q"*2 + "I"*4,
            buf)
    tcpi_rtt = tcp_info[8+15]       # µs
    # note: potentially of interest regarding the rtt too, we have:
    # tcpi_rtt_var = tcp_info[8+16]
    # tcpi_rcv_rtt = tcp_info[8+21]
    # tcpi_min_rtt = tcp_info[8+24+4+3]
    # But tcpi_rtt gives good results.
    return tcpi_rtt


class ClockSyncListener:
    REQ_ID = Requests.REQ_CLOCK_SYNC

    def __init__(self, ev_loop, sock_file, **kwargs):
        self._ev_loop = ev_loop
        self._sock_file = sock_file

    def fileno(self):
        return self._sock_file.fileno()

    def handle_event(self, ts):
        if self._sock_file is None:
            return False
        msg = self._sock_file.read(5)  # expect b'SYNC\n'
        self._sock_file.set_nodelay()
        # On node side, busybox can only set the date with a 1-second
        # granularity,so we wait until next second change before sending
        # the date as an integer.
        # We actually send the message a little earlier to take into
        # account the one-way-delay. The RTT is obtained by using
        # getsockopt(TCP_INFO), see get_rtt_us() above. We have to convert
        # the RTT to seconds and divide it by 2 (RTT->OWD), thus the
        # 0.0000005 factor.
        rtt_us = get_rtt_us(self._sock_file.sock)
        owd_s = rtt_us * 0.0000005
        now = time()
        clock_ts = int(now + 1)
        evt_ts = clock_ts - owd_s
        if now >= evt_ts:
            clock_ts += 1
            evt_ts = clock_ts - owd_s
        self._ev_loop.plan_event(
            ts=evt_ts,
            target=self,
            clock_ts=clock_ts,
            evt_ts=evt_ts)
        return True

    def close(self):
        if self._sock_file:
            self._sock_file.close()
            self._sock_file = None

    def handle_planned_event(self, clock_ts, evt_ts):
        # return timestamp and unblock the node
        print(time()-evt_ts)
        self._sock_file.write(f"{clock_ts}\n".encode())
        self._sock_file.close()
        self._sock_file = None


class ClockSyncManager:
    """Walt nodes bootup synchronization handler.

    walt nodes get approximate time synchronization at
    bootup by requesting a unix timestamp from the server.
    It is of course possible (and recommended) to install a
    more precise synchronization protocol (preferably PTP)
    into the image.
    """

    def __init__(self, tcp_server, ev_loop):
        for cls in [ClockSyncListener]:
            tcp_server.register_listener_class(
                req_id=cls.REQ_ID, cls=cls, ev_loop=ev_loop
            )
