import fcntl, os, stat, struct
from pathlib import Path

TUNSETIFF = 0x400454ca
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000
TUN_DEV_MAJOR = 10
TUN_DEV_MINOR = 200

# create a TAP device
def createtap():
    devpath = Path('/dev/net/tun')
    if not devpath.exists():
        devpath.parent.mkdir(parents=True, exist_ok=True)
        os.mknod(str(devpath), stat.S_IFCHR | 0o666, os.makedev(TUN_DEV_MAJOR, TUN_DEV_MINOR))
    tap = open('/dev/net/tun', 'r+b', buffering=0)
    # Tell it we want a TAP device and no packet headers
    ifr = bytearray(struct.pack('16sH', b'', IFF_TAP | IFF_NO_PI))
    fcntl.ioctl(tap, TUNSETIFF, ifr)
    # Retrieve kernel chosen TAP device name
    tap_name = struct.unpack('16sH', ifr)[0].decode('ascii').strip('\x00')
    print('created ' + tap_name)
    return tap, tap_name
