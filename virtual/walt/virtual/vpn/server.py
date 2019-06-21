import os, socket
import subprocess
from select import select
from pathlib import Path
from walt.virtual.tools import createtap
from walt.virtual.vpn.const import VPN_SOCK_PATH, VPN_SOCK_BACKLOG

BRIDGE_INTF = "walt-net"

def run():
    # Create TAP
    tap, tap_name = createtap()

    # Bring it up, add it to bridge
    subprocess.check_call('ip link set up dev ' + tap_name, shell=True)
    subprocess.check_call('ip link set master ' + BRIDGE_INTF + ' dev ' + tap_name, shell=True)

    print('added ' + tap_name + ' to bridge ' + BRIDGE_INTF)

    # create the VPN server socket
    sock_path = Path(VPN_SOCK_PATH)
    if sock_path.exists():
        sock_path.unlink()
    s_serv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s_serv.bind(VPN_SOCK_PATH)
    s_serv.listen(VPN_SOCK_BACKLOG)
    sock_path.chmod(0o777)  # allow other users to connect

    # start select loop
    # we will just:
    # * accept all clients that connect to /var/run/walt-vpn.sock
    # * transfer packets coming from a client to the tap interface
    # * transfer packets coming from the tap interface to all clients
    fds = [ s_serv, tap ]
    while True:
        r, w, e = select(fds, [], [])
        if len(r) == 0:
            break
        r_obj = r[0]
        if r_obj == s_serv:
            s_client, addr = s_serv.accept()
            fds.append(s_client)
            continue
        if r_obj == tap:
            w_objs = fds[2:]    # write to all clients
            print('writing to', len(w_objs), 'peers')
        else:
            w_objs = [ tap ]    # write to tap
            print('writing to tap')
        packet = os.read(r_obj.fileno(), 2048)
        if len(packet) == 0:
            if r_obj == tap:
                # unexpected, let's stop
                break
            else:
                # client is probably disconnected
                fds.remove(r_obj)
                r_obj.close()
                continue
        for w_obj in w_objs:
            os.write(w_obj.fileno(), packet)
