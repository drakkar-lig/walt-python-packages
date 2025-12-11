
# Enabling RAM swapping on WalT nodes

In their default boot mode, WalT nodes store the created or modified files
in a RAM overlay, in order to keep the WalT image read-only and implement
a concept of **reproducibility at each reboot**.
See [`walt help show boot-modes`](boot-modes.md) for more info.

In order to avoid exhausting this thin layer of RAM space, WalT nodes can
make use of a swap device.


## Regular swap partition

The bootup scripts of WalT nodes will automatically scan the disks and then
detect and mount any **swap partition**.
So users may just format a swap partition on a local disk to enable
this technique.
Note however that local swap usage is disabled for Raspberry Pi 5 nodes,
since they may be used as VPN nodes and local swap could be used as a
security breach.

On a virtual node, this is even simpler. One just has to add a virtual
disk with the `swap` template. For instance:
`walt node config <vnode> disks=32G[template=swap]`

After a reboot, `<vnode>` will make use of this swap space.


## Remote swap space

WalT nodes may alternatively mount a **network swap device** at bootup,
if the WalT OS image provides the "Network Block Device" client software.
It is called `nbd-client` in Debian-based systems.

In this case, when the node starts swapping, the data is actually stored
in a temporary file on the WalT server.

Note however that this technique is not 100% reliable and may cause
unexpected OS issues in extreme situations. If you make heavy use of the
swap space, prefer a regular swap partition or a different boot mode.
You may also reduce your swap usage by leveraging `/persist` for storing
files, and reducing the amount of new files created on the node by
preparing more things in advance in the WalT image.
See [`walt help show boot-modes`](boot-modes.md).

Note that if a local swap partition was mounted this remote swap space
is disabled, even if `nbd-client` is available in the OS image (because
local swap is more reliable).
