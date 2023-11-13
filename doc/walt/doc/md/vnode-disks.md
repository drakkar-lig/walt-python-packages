
# Configuring disks on virtual nodes

## Basics

By default virtual nodes have no disk configured.
Since they boot over the network, a network interface in enough.

However, for specific experiments, one can easily reconfigure virtual nodes
to attach one or more disks to them.

For instance, here is how one can attach two disks of different size to `vnode1` and `vnode2`:

```
$ walt node config vnode1 disks=32G,1T
```

After rebooting, `vnode1` will get the two disks requested.
They are named `/dev/sda` and `/dev/sdb` on most WalT OS images.

It is also possible to define those disks on several virtual nodes at once:

```
$ walt node config vnode1,vnode2 disks=32G,1T
```


## Impact on server storage

Disks are implemented as a file of the requested size on server-side. However, these files
have a minimal impact on server disk space, since they are first created as a large hole.
Next, only the sectors really written on these disk files will consume server disk space.

For instance, if your walt server only has 256GB of disk space left, you can still create
a large disk of say 1T on a virtual node. This will only become a problem if this virtual node
really saves more than 256GB of data inside this disk.


## Disk templates

By default, disks are left unconfigured. WalT users can format them as they wish,
using standard tools (e.g., `fdisk`, `mkfs`) when the virtual node is booted.

However, for convenience, WalT proposes a few disk templates:
```
$ walt node config vnode2 disks=32G[template=ext4],1T
```

In this example, the first disk will be configured with the `ext4` template, and
the second one will be left unconfigured.

`walt node config` understands the following disk templates:
* `ext4`: one single partition with `ext4` filesystem
* `fat32`: one single partition with `FAT32` filesystem
* `none`: the disk is left unconfigured (same effect as not defining the template)
* `hybrid-boot-v`: the disk is configured to activate the hybrid boot method (volatile variant) on this node.
* `hybrid-boot-p`: the disk is configured to activate the hybrid boot method (persistent variant) on this node.

See [`walt help show boot-modes`](boot-modes.md) for more info about hybrid boot modes.

