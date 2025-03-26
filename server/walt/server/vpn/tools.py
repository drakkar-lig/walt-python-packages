import fcntl
import os
import stat
import struct
import sys
from pathlib import Path

TUNSETIFF = 0x400454CA
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000
TUN_DEV_MAJOR = 10
TUN_DEV_MINOR = 200


# create a TAP device
def createtap():
    devpath = Path("/dev/net/tun")
    if not devpath.exists():
        devpath.parent.mkdir(parents=True, exist_ok=True)
        os.mknod(
            str(devpath), stat.S_IFCHR | 0o666, os.makedev(TUN_DEV_MAJOR, TUN_DEV_MINOR)
        )
    tap = open("/dev/net/tun", "r+b", buffering=0)
    # Tell it we want a TAP device and no packet headers
    ifr = bytearray(struct.pack("16sH", b"", IFF_TAP | IFF_NO_PI))
    fcntl.ioctl(tap, TUNSETIFF, ifr)
    # Retrieve kernel chosen TAP device name
    tap_name = struct.unpack("16sH", ifr)[0].decode("ascii").strip("\x00")
    print("created " + tap_name)
    return tap, tap_name


def read_n(fd, n):
    buf = b""
    while len(buf) < n:
        chunk = os.read(fd, n - len(buf))
        if len(chunk) == 0:
            # short read!
            break
        buf += chunk
    return buf


DEBUG_OUT = None


def enable_debug(out=sys.stdout):
    global DEBUG_OUT
    DEBUG_OUT = out


def debug(*args):
    if DEBUG_OUT is not None:
        from time import time

        print(time(), *args, file=DEBUG_OUT)
        DEBUG_OUT.flush()
