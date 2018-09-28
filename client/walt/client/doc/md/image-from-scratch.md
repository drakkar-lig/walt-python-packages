# Creating a WalT image from scratch

Most users just need to modify existing images built by other users, such as the official images build by walt platform developers (with docker user `waltplatform`). In order to modify an image easily, they can use `walt image shell` or `walt image cp`. However, for specific needs, it is sometimes useful to create a whole new operating system image for WalT. This page describes how to achieve this.

This procedure is dedicated to advanced users that are familiar with operating systems operation and `docker` classical tools.

## A) Introduction

A WalT image is just a [docker image](https://docs.docker.com/engine/getstarted/); as such, you can use docker usual procedure to build it:
* create a Dockerfile
* use the `docker build` command
* use the `docker push` command to push it to the docker hub

After this, you should let WalT rescan your docker hub account by typing:
```
$ walt advanced rescan-hub-account
```
(Before you run this, WalT has no knowledge about this new image, since you did not use WalT to create it.)

A small set of features is required to make your image work with WalT. The next section lists them. Then, another section describes a few optional features you could also benefit from.

## B) Mandatory features

In order to run properly as a WalT image, a [docker image](https://docs.docker.com/engine/getstarted/) should provide:

### 1- a docker label specifying compatible models

All WalT images should provide a label `walt.node.models` specifying which node models this image can boot.
Without this label, the image will be ignored.

For example, the Dockerfile of an image for `rpi-b` and `rpi-b-plus` models should be:

```
FROM <base-image>
LABEL walt.node.models="rpi-b,rpi-b-plus"
[...]
```

Notes:
* This comma-separated format is mandatory (even if WalT will try to print it in a more compact way in commands output).
* Whenever you push to docker hub a new version of your image with this setting modified, you have to call `walt advanced rescan-hub-account` again.

### 2- appropriate boot files

When booting, the node starts its network bootloader stored locally (on a SD card, in a flash memory, on a bootable USB device, etc.).
Then it will use the TFTP protocol to download a second-stage boot script.
The name of this second-stage boot script depends on the network bootloader. Here are some examples:
* `/start.ipxe` for ipxe
* `/start.uboot` for u-boot

The TFTP service installed on WalT server redirects TFTP requests for a file at `<path>` to `[image_root]/boot/<node_model>/<path>`.
For example, a `rpi-b-plus` node sending a TFTP request for file `/start.uboot` will actually get file `[image_root]/boot/rpi-b-plus/start.uboot`.

As a result, the image should provide a directory `/boot/<node_model>` for each node model handled. This directory should contain the second-stage boot script and resources needed by this script (kernel, maybe an initrd, maybe a device tree blob, etc.), or symbolic links if these resources are stored elsewhere in the image.

### 3- kernel features

For a raspberry pi kernel, see https://www.raspberrypi.org/documentation/linux/kernel/building.md.

The provided kernel(s) should include the following:

* `CONFIG_OVERLAY_FS=y`   # overlay filesystem
* `CONFIG_NFS_FS=y`       # nfs client
* `CONFIG_NFS_V3=y`       # nfs client v3
* `CONFIG_ROOT_NFS=y`     # root filesystem on NFS
* `CONFIG_IP_PNP=y`       # kernel network autoconf
* `CONFIG_IP_PNP_DHCP=y`  # kernel dhcp autoconf

You should also include the device driver for your network card, for instance `CONFIG_IGB=y` for Intel cards.

If you use an initrd, some of these features (such as `CONFIG_OVERLAY_FS`) may be built as kernel modules (`=m` instead of `=y`) and others may be omitted (such as `CONFIG_ROOT_NFS`). If not, building all these features into the kernel (`=y`) is mandatory, and in any case, it is safe to do it.

### 4- an init system

The init system of your image should be available at `/sbin/init`.

### 5- busybox and classical unix commands

For proper handling of the bootup procedure, you should embed a static version of busybox at `/bin/busybox` (on a debian-based image: `apt-get install busybox-static`).
This busybox binary should at least include the following applets: `chroot` `ls` `mktemp` `mkfifo` `nc` `reboot` `sed` `sh` `sleep` `timeout`.

The following commands should also be provided in the image (either through `busybox` applets or not, it does not matter):
`awk` `cat` `chmod` `chroot` `cp` `date` `echo` `grep` `head` `ln` `mkdir` `mount` `reboot` `sed` `setsid` `sh` `timeout` `tr` `umount`.

### 6- a ssh server set up to listen on port 22

The ssh server configuration should allow root access when using public key authentication.

When deploying your image, the WalT server will automatically insert its own public key in file `/root/.ssh/authorized_keys`. This allows the WalT server to offer shell sessions and file transfers to or from the node.

In the case of openssh, `PermitRootLogin without-password` in `/etc/ssh/sshd_config` should be enough.

For low-power devices, consider using [dropbear](https://matt.ucc.asn.au/dropbear/dropbear.html).

## C) Optional features

Supporting the following options will add more features to your walt image.

### 1- lldp daemon

LLDP (link layer discovery protocol) allows the WalT server to locate your node inside the layer-2 network, and thus display the network topology appropriately when calling `walt device tree`.

### 2- precise time synchronization

WalT bootup scripts will automatically synchronize node's clock with the server at bootup. For a more precise synchronization between nodes, and to avoid clock drift over the long term, a network synchronization protocol is needed.

PTP (Precision Time Protocol) is the preferred synchronization protocol.
The WalT server is a PTP master.

For reference, the images we provide come with the following configuration files:

```
$ cat /etc/default/ptpd
# /etc/default/ptpd

# Set to "yes" to actually start ptpd automatically
START_DAEMON=yes

# Add command line options for ptpd
PTPD_OPTS="-c /etc/ptpd.conf"

$ cat /etc/ptpd.conf
ptpengine:interface=eth0
ptpengine:preset=slaveonly
global:cpuaffinity_cpucore=0
global:ignore_lock=Y
global:log_file=/var/log/ptpd.log
global:log_status=y
ptpengine:domain=42
ptpengine:ip_dscp=46
ptpengine:ip_mode=hybrid
ptpengine:log_delayreq_interval=3
$
```

An alternative protocol is NTP (Network Time Protocol), also available on server side. However using NTP is discouraged because synchronization is much slower and less stable.
A working configuration would be in this case:

```
$ cat /etc/ntp.conf
driftfile /var/lib/ntp/ntp.drift

statistics loopstats peerstats clockstats
filegen loopstats file loopstats type day enable
filegen peerstats file peerstats type day enable
filegen clockstats file clockstats type day enable

server %(server_ip)s

restrict -4 default kod notrap nomodify nopeer noquery
restrict -6 default kod notrap nomodify nopeer noquery

restrict 127.0.0.1
restrict ::1

$
$ cat /etc/walt/image.spec
{
    "templates": [
        "/etc/ntp.conf"
    ]
}
$
```

As you can see, NTP configuration requires the IP address of the NTP server. In this case, this is the IP of WalT server. As a result, this IP could vary depending on the WalT platform where this image will be used. To overcome this issue, we use the image templating system (see [`walt help show image-spec-file`](image-spec-file.md)). WalT server will automatically replace the pattern `%(server_ip)s` in file `/etc/ntp.conf` when the image is mounted.

### 3- multicast DNS

Installing multicast DNS management in an image is handy for communicating between nodes, since nodes can be reached by targeting `<node-name>.local`. For example:

```
root@rpi-ble1:~# ping rpi-ble2.local
PING rpi-ble2.local (192.168.152.198) 56(84) bytes of data.
64 bytes from 192.168.152.198: icmp_seq=1 ttl=64 time=1.73 ms
64 bytes from 192.168.152.198: icmp_seq=2 ttl=64 time=0.879 ms
...
```

On a debian-based image, mDNS may be installed by running:

```
$ apt-get install avahi-daemon libnss-mdns
```

### 4- walt-node python package

If your image provides python2.7 and systemd, you can install the walt-node python package:

```
$ pip install walt-node
```

This will provide enhanced walt logging features (see [`walt help show logging`](logging.md)). Note that without this package, you can still use the standard logging features.

### 5- led-blinking script

The `walt node blink <node-name>` command may be used to visually identify a node, by making a led blink.

This will work only if the image provides an executable file at `/bin/blink`. Calling `/bin/blink 1` should make the led start to blink, `/bin/blink 0` should make it stop.

