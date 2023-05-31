import os
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from subprocess import check_call, check_output

BRIDGE_INTF = "walt-net"


@contextmanager
def temporary_network_pipe():
    # generate a unique name
    pipe_name = "pipe-%d" % os.getpid()
    pipe = ("%s-0" % pipe_name, "%s-1" % pipe_name)
    # create pipe
    check_call(
        "ip link add %(pipe0)s type veth peer name %(pipe1)s"
        % dict(pipe0=pipe[0], pipe1=pipe[1]),
        shell=True,
    )
    try:
        yield pipe
    finally:
        # release pipe (note: the other end is automatically removed)
        check_call("ip link del " + pipe[0], shell=True)


UDHCPC_SCRIPT = """\
#!/bin/sh
if [ "$ip" = "" ]
then
    exit 0
fi
echo VAR hostname $hostname
echo VAR ip $ip
echo VAR server_ip $serverid
echo VAR gateway $router
echo VAR netmask $subnet
"""


def udhcpc_get_vars(env, interface):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        script = tmpdir / "script.sh"
        script.write_text(UDHCPC_SCRIPT)
        script.chmod(0o755)  # make it executable
        info = check_output(
            "udhcpc -V %(vci)s -f -q -n -i %(interface)s -s %(script)s"
            % dict(vci=env["vci"], interface=interface, script=str(script)),
            shell=True,
        ).decode(sys.getdefaultencoding())
        for line in info.splitlines():
            words = line.split()
            if words[0] != "VAR":
                continue
            if len(words) == 3:
                var_name, value = words[1], words[2]
            else:
                var_name, value = words[1], ""
            env[var_name] = value


def udhcpc_setup_interface(env, interface):
    check_call(
        "udhcpc -V %(vci)s -f -q -n -i %(interface)s"
        % dict(vci=env["vci"], interface=interface),
        shell=True,
    )


# 1. We create a set of temporary "veth" interfaces. One end is linked to
#    walt-net bridge. The other end is configured with the mac address we
#    will use later for the walt node.
# 2. We use udhcpc to get the network parameters we were missing.
#    Because of the mac address, the server will consider this request comes
#    from the node.
# 3. We clean things up by removing temporary "veth" interfaces.


@contextmanager
def udhcpc_fake_netboot(env):
    bridge_dev_dir = Path("/sys/class/net") / BRIDGE_INTF
    while not bridge_dev_dir.is_dir():
        print("'%s' not available yet. Will retry in a moment." % BRIDGE_INTF)
        time.sleep(3)
    with temporary_network_pipe() as pipe:
        check_call(
            "ip link set dev %(pipe0)s master %(bridge)s up"
            % dict(pipe0=pipe[0], bridge=BRIDGE_INTF),
            shell=True,
        )
        check_call(
            "ip link set dev %(pipe1)s address %(mac)s up"
            % dict(pipe1=pipe[1], mac=env["mac"]),
            shell=True,
        )
        try:
            # we need to save env variables retrieved through DHCP
            # (they are needed to interpret ipxe scripts)
            udhcpc_get_vars(env, pipe[1])
            # we also need to setup the interface to handle TFTP transfers
            udhcpc_setup_interface(env, pipe[1])
            yield True
        except Exception:
            traceback.print_exc()
            yield False
