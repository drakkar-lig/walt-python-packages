# Creating a WalT image from scratch

Most users just need to modify existing images built by other users, such as the official images build by walt platform developers (with docker user `waltplatform`). In order to modify an image easily, they can use `walt image shell`, [`walt image cp`](image-cp.md) or [`walt image build`](image-build.md). However, for specific needs, it is sometimes useful to create a whole new operating system image from scratch.
For instance, this is sometimes required for the support of a new kind of node in WALT.

This procedure is dedicated to advanced users that are familiar with operating systems operation and docker-related tools.

## A) Introduction

A WalT image is just a [docker image](https://docs.docker.com/engine/getstarted/), so it is easy to build an image
using a Dockerfile. Check-out [`walt help show image-build`](image-build.md) for reference.

However, most users use an existing WALT image (usually the default one for the node model) as a starting point, and
just define the additional build steps needed for a specific experiment.
Here, we describe how to define the whole image from scratch.

A small set of features is required. The next section lists them. Then, another section describes a few optional features you could also benefit from.

## B) Mandatory features

In order to run properly as a WalT image, a [docker image](https://docs.docker.com/engine/getstarted/) should provide:

### 1- A label "walt.node.models"

All WalT images should provide a label `walt.node.models` specifying which node models this image can boot.
Without this label, the image will be ignored.

For example, the Dockerfile of an image for `rpi-b` and `rpi-b-plus` models should be:

```
FROM <base-image>
LABEL walt.node.models="rpi-b,rpi-b-plus"
[...]
```

Note: This comma-separated format is mandatory (even if WalT will try to print it in a more compact way in commands output).

### 2- A label "walt.server.minversion"

This label allows to specify the minimum server version this image was built for.
For example:

```
LABEL walt.server.minversion="5"
```

Notes:
* Management of this label was introduced in walt version 5. Thus, if not found in an image, the default value for this label is 4.
* This label allows to handle changes in the minimum set of software an image should provide. For instance, a busybox syntax change between debian 9 and debian 10 prevents proper node bootup on walt server version 4. Thus version 5 was modified to allow both syntax forms, and buster images were built with label `walt.server.minversion` set to 5.

### 3- appropriate boot files

When booting, the node starts its network bootloader stored locally (on a SD card, in a flash memory, on a bootable USB device, etc.).
Then it will use the TFTP protocol to download a second-stage boot script.
The name of this second-stage boot script depends on the network bootloader. Here are some examples:
* `/start.ipxe` for ipxe
* `/start.uboot` for u-boot

The TFTP service installed on WalT server redirects TFTP requests for a file at `<path>` to `[image_root]/boot/<node_model>/<path>`.
For example, a `rpi-b-plus` node sending a TFTP request for file `/start.uboot` will actually get file `[image_root]/boot/rpi-b-plus/start.uboot`.

As a result, the image should provide a directory `/boot/<node_model>` for each node model handled. This directory should contain the second-stage boot script and resources needed by this script (kernel, maybe an initrd, maybe a device tree blob, etc.), or symbolic links if these resources are stored elsewhere in the image.

For detailed information of the node bootup procedure, see [`walt help show node-bootup`](node-bootup.md).

### 4- kernel features

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

### 5- an init system

The init system of your image should be available at `/sbin/init`.

### 6- busybox and classical unix commands

For proper handling of the bootup procedure, you should provide a `busybox` multi-call binary at `/bin/busybox`.
This busybox binary should at least include the following applets: `awk` `cat` `chroot` `ls` `mktemp` `mkfifo` `nc` `realpath` `reboot` `rm` `sed` `sh` `sleep` `timeout` `uname`.
If this busybox binary is not statically compiled (on a debian-based image: `apt-get install busybox-static`), you must also provide a `ldd` binary.

The following commands should also be provided in the image (either through `busybox` applets or not, it does not matter):
`chmod` `chroot` `cp` `date` `echo` `grep` `head` `ln` `mkdir` `mount` `reboot` `sed` `setsid` `sh` `timeout` `tr` `umount`.

### 7- a ssh server set up to listen on port 22

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

If your image provides python3.6+ and systemd, you can install the walt-node python package:

```
$ pip3 install walt-node
$ walt-node-setup
```

This will provide:
* Enhanced walt logging features (see [`walt help show logging`](logging.md)). Note that without this package, you can still use the standard logging features.
* Tool `walt-ipxe-kexec-reboot`, allowing to implement faster reboots. This only works if the image is based on iPXE boot scripts and has kexec tool installed. To enable this, link this command to `/bin/walt-reboot` (see below).

### 5- led-blinking script

The `walt node blink <node-name>` command may be used to visually identify a node, by making a led blink.

This will work only if the image provides an executable file at `/bin/blink`. Calling `/bin/blink 1` should make the led start to blink, `/bin/blink 0` should make it stop.

### 6- custom reboot script

If the image provides an executable command `/bin/walt-reboot`, then this command will be called when (soft-)rebooting the node.

Providing this file may be useful in various cases. For instance:
* Ensuring a result file is flushed in `/persist` before rebooting
* Providing a faster way to reboot, e.g. kexec

If `/bin/walt-reboot` returns, even successfully, the calling script `walt-net-service` will consider the reboot failed and run `busybox reboot -f`.

Caution: if providing an advanced way to reboot (e.g. kexec), one must take care not blindly rebooting the same kernel and initrd: the node may have been associated to a different image.

### 7- label "walt.image.preferred-name"

If this image will be the default image for several new node models, one may specify this label to indicate the "preferred image name" (see explanation below).
For example:

```
LABEL walt.image.preferred-name="rpi-default:latest"
```

When a new user types `walt image show` for the first time, a set of default images is automatically cloned. These are the default images for the node models already present on the platform.
However, a default image often handles several node models. For instance, the default image for raspberry pi boards can handle all B models, from rpi-b to rpi-4-b. In earlier walt versions, the new user obtained various clones of this image, named `rpi-b-default`, `rpi-b-plus-default`, ... and `rpi-4-b-default` (as long as all these models are present on the platform). Now only one clone will be created, and it will be named according to this label if defined.

### 8- /etc/cpuinfo file

When users will be running `walt image shell` on your new image, some (rare) programs may fail: those that try to guess the CPU architecture by reading file `/proc/cpuinfo`.
Since the filesystem mounted at `/proc` is linked to the linux kernel running on the host, the content of this file shows information about the host CPU, instead of the expected target node CPU.
An example of those failing commands is `yum` package manager often installed in rpm-based systems.
In order to handle this case properly, you may dump the file `/proc/cpuinfo` of a running target node, and provide this file at `[image_root]/etc/cpuinfo`.
If this file is found in the image, walt server will bind-mount it at `/proc/cpuinfo`, which should solve this problem.

### 9- Support for an advanced virtual environment in `walt image shell`

By default, `walt image shell` is just implemented by running a shell (`bash` or `sh`) in a container created from the image.
On user exit, the changes are saved as a new image.
But this basic virtual environment with only the shell process is too minimalist for some cases. See [`walt help show shells`](shells.md) for more details.

As an alternative, you can add support for an advanced virtual environment in `walt image shell`, where the OS init is started when the shell starts, and shut down when it exits.
For this, provide the following files with execution bits set:
* `[image_root]/bin/walt-image-shell-start`
* `[image_root]/bin/walt-image-shell-shutdown`

`/bin/walt-image-shell-start` is expected to eventually call `exec /sbin/init`, and possibly perform a little tuning before that point for the init system to run well in the container environment. For instance, in the systemd-based images we provide, we temporarily rename `/etc/network/interfaces`. Otherwise systemd will try to initialize `lo` (loopback interface), which fails because the container environment already initialized it.
`/bin/walt-image-shell-shutdown` is expected to undo the tuning done by `/bin/walt-image-shell-start` and then request the init system to halt (e.g, `init 0`).

When these files are provided, the WALT server performs these steps:
1. Run the container in the background with `walt-image-shell-start` (i.e., `podman run -d --entrypoint /bin/walt-image-shell-start [...]`)
2. Start the shell in an `exec` interactive session (i.e., `podman exec -it $container_id $shell`)
3. When the shell session (step 2) ends, call `podman exec $container_id /bin/walt-image-shell-shutdown`
4. Similarly to the basic case, wait for the background container to end, then save changes to a new image, etc.

Note that this procedure hides the startup messages of the init system (steps 1 and 3) to the user.
For debugging, you can work on an image without `/bin/walt-image-shell-start` or `/bin/walt-image-shell-shutdown` at first, so just a basic virtual environment is set when you run `walt image shell`. In this basic environment, you can test the commands you wish to embed in those files one by one, for instance `exec /sbin/init`, and verify that everything can run properly in a container environment.

### 10- Support for RAM swapping using NBD

If the OS image supports it, the node will be able to use a Network Block Device (NBD) for RAM swapping.
It is quite an interesting feature, because heavy file modifications on the nodes (e.g., package installations) fail otherwise, since they are stored in a RAM overlay with limited size.
See [`walt help show boot-modes`](boot-modes.md) for more info.

To support this, the image must provide commands `nbd-client`, `mkswap`, `swapon` and the kernel module called `nbd`.
