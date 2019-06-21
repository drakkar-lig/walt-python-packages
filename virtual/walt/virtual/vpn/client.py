import os, os.path, sys
from subprocess import check_call, Popen, PIPE
from select import select
from walt.virtual.tools import createtap

BRIDGE_INTF = "walt-net"
USAGE='''\
Usage:
$ %(prog)s ssh [options] walt-vpn@<walt-server> walt-vpn-endpoint

Note: in order to avoid exposing walt server to the wild, <walt-server>
is usually replaced by an appropriately configured ssh proxy.
'''

def run():
    # Verify args
    if len(sys.argv) < 2:
        print(USAGE % dict(prog = os.path.basename(sys.argv[0])), end='')
        sys.exit()

    # Create TAP
    tap, tap_name = createtap()

    # Bring it up, add it to bridge
    check_call('ip link set up dev ' + tap_name, shell=True)
    check_call('ip link set master ' + BRIDGE_INTF + ' dev ' + tap_name, shell=True)

    print('added ' + tap_name + ' to bridge ' + BRIDGE_INTF)

    # Start the command to connect to server
    popen = Popen(sys.argv[1:], stdin=PIPE, stdout=PIPE, bufsize=0)

    # start select loop
    # we will just:
    # * transfer packets coming from the tap interface to ssh stdin
    # * transfer packets coming from ssh stdout to the tap interface
    fds = [ popen.stdout, tap ]
    while True:
        r, w, e = select(fds, [], [])
        if len(r) == 0:
            break
        r_obj = r[0]
        if r_obj == tap:
            w_obj = popen.stdin     # tap -> cmd channel
        else:
            w_obj = tap             # cmd channel -> tap
        packet = os.read(r_obj.fileno(), 2048)
        if len(packet) == 0:
            break
        os.write(w_obj.fileno(), packet)
