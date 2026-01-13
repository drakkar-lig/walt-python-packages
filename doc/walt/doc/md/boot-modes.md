
# Boot modes of WalT nodes

## Introduction

Different boot modes are available for WalT nodes:
* `network-volatile` (the default)
* `network-persistent`
* `hybrid-volatile`
* `hybrid-persistent`

Use `walt node config <node-name> boot.mode=<mode>` to change it.
See [`walt help show device-config`](device-config.md).

However, when switching to an `hybrid` boot mode, an `ext4` partition
must be available on a local disk of the node (or SD card). If not,
it will fallback to the default boot mode.
See "Hybrid boot details" below.


## Volatile and Persistent boot modes

Boot modes tagged `volatile` ease experiment reproducibility.
Each time the node reboots, it discards all changes made on files
(created, removed, modified), and restarts from the original files of
the OS image. This ensures that a node booting a given image will always
act the same. We call this technique **Reproducibity at each reboot**.

Users leverage `volatile` boot modes when they want to launch `N` runs
of an experiment. They first edit the OS image to launch the
experiment scripts automatically when the node boots (e.g., by adding
a `systemd` service). Then, running the `N` runs of the experiment
just means rebooting the nodes `N` times.

For keeping track of experiment results, users may use the logging
features (cf. [`walt help show logging`](logging.md)), or store
result files in the directory `/persist`, which is explicitely excluded
from this volatile behavior and always preserved accross reboots
(cf. [`walt help show slash-persist`](slash-persist.md)).

At the contrary, boot modes tagged `persistent` have a behavior which
may seem more usual to new users: the OS of the node diverges from the
original OS image over time.

The `persistent` boot modes are useful in the case of **long term
deployment of a WalT node**. For instance, if we want to deploy a
Raspberry Pi node equipped with a LoRa gateway board, we may use the
OS image published on the Docker Hub under the name `rpi32-chirpstack`.
However, after booting the node, some configuration might still be
needed on the web interface the OS provides (e.g., for indicating a
remote LNS server). Switching to a `persistent` boot mode avoids losing
this configuration and any data gathered by the node each time it reboots.


## Network and Hybrid boot techniques

Boot modes with prefix `network-` are based on network boot, a booting
technique avoiding the use of local storage on the node. This allows
switching between OS images in a snap: there is no need to transfer
the OS image in its entirety to the node, nor to write it to its disk.

A WalT node with a boot mode prefixed `hybrid-` instead transfers and
copies the OS image from the server to its local storage and then boots
from it. This technique is called `hybrid` because the very first steps
of the boot procedure still rely on the network.

The known reasons for switching to an hybrid boot mode are:
* The experiment involves I/O disk performance tests, or
* The experiment lets the node create many big files, so storing
  them in `/persist` would have a high impact on performance, and
  storing the `Diff` in RAM or remotely on the server would cause
  stability or performance issues (see next section).


## How read-only OS images are shared among nodes

In the case of WalT, an OS image always remains read-only, because it may
be shared among several nodes. However, in order to let each node create
or modify its own files, an "overlay" (or "Diff") layer implementing
copy-on-write semantics is mounted on top of it.

The following table indicates how a node interacts with its OS image and
its own Diff, depending on its boot mode.

| Boot mode          | OS image location     | Diff location         |
|--------------------|-----------------------|-----------------------|
| network-volatile   | remote, on the server | RAM of the node       |
| network-persistent | remote, on the server | remote, on the server |
| hybrid-volatile    | copy on local storage | on local storage      |
| hybrid-persistent  | copy on local storage | on local storage      |

The `volatile` property is implemented by discarding the `Diff` at each
reboot. In the case of `network-volatile`, this is implicit since the
`Diff` is stored in RAM, and RAM is volatile itself. In the case of
`hybrid-volatile`, the node explicitly discards the `Diff` contents as
part of its bootup procedure.


## Limits of the `network-volatile` boot mode

In the `network-volatile` boot mode, the `Diff` is stored in RAM,
which means that creating many big files may lead to RAM space
exhaustion.

One way to avoid this is to let the node use a swap device.
See [`walt help show node-swap`](node-swap.md).
However, note that swapping can reduce the reproducibility of an
experiment and might cause OS issues in extreme situations.

The following tips are usually a better alternative:
* Whatever the boot mode, **a good practice with WalT is to automate
  experiment preparation steps as much as possible in the WalT OS image**,
  and not run them on the node. This is all the more important when
  using the `network-volatile` boot mode, because it will much reduce
  the usage of the `Diff`. You can use `walt image shell` or
  `walt image build` to prepare the OS images and run any command
  heavy on the file system (such as installing OS packages).
  If a part of your setup procedure uses `walt node save`, it should
  be called with an image where those preliminary steps heavy on the
  file system have already been applied.
* **Large experiment result files should be generated in the directory
  `/persist` of the node**, since this directory is excluded from the
  RAM `Diff`. See [`walt help show slash-persist`](slash-persist.md).

Sometimes, one may also use the local disk(s) of a node as storage
for a part of the experiment, and let the `network-volatile` boot
mode manage the OS files. It is easy to add disks to virtual nodes
(see [`walt help show vnode-disks`](vnode-disks.md) for more info).


## Network boot details

In the case of network-based boot modes, the OS image remains on the
WalT server only: it is never transfered as a whole to the node(s).
Instead, the node sends network requests to the server each time it
needs to access a file or directory.
In a sense, compared to booting on a local disk, network booting just
means using the network controller to read OS files and metadata instead
of the disk controller.

This setup has the following pros:
* **Near-zero OS deployment delay.** Instead of transfering a whole OS
  image from the server to the node's disk, the server just updates a
  symlink to target the proper OS image and sends a reboot request to the
  node. One could argue that network transfers happen once the node is
  booting instead, but the method remains very frugal on network
  resources: only the files and metadata that are actually necessary are
  transferred, which is typically less than 10% of the total OS image size.
* **Reduced platform maintenance burden.** The local disks or SD cards of
  the nodes are usually the most fragile components of a platform, so
  avoiding their use is often preferable.


## Hybrid boot details

The hybrid boot mode instructs the node to copy the OS image contents
to its local storage and then boot from it.

Whatever the boot mode, the procedure is always network-based at first
(i.e., targetting the proper WalT OS image, and then downloading and
running the kernel this image contains). But then, when an hybrid boot
mode is selected, `walt-init` scripts scan local disks (or SD cards)
and look for an ext4-formatted partition. This partition is used for
storing the OS image copy and the `Diff` directory, and the node boots
from there.

For security reasons, hybrid boot modes are not allowed for VPN nodes.
Moreover, hybrid boot may fail sometimes (no storage device detected, no
ext4-formatted partition detected, the partition is too small, etc.).
In all thoses cases, the node falls back to the default boot mode,
`network-volatile`, and the node emits relevant log lines with stream
name `walt-init` (cf. [`walt help show logging`](logging.md)).

Using virtual nodes, it is easy to prepare the node for an hybrid boot:
just add a disk with template `ext4`.
(See [`walt help show vnode-disks`](vnode-disks.md) for more info.)

Important notes:
* The first time a node boots an image in hybrid mode, the bootup time
  will be longer (up to several minutes longer, depending on network,
  disk, and image size) because of the complete copy of the WalT image
  to the local disk.
* The default partitionning of SD cards usually involves a single
  FAT32 partition. Preparing hybrid boot modes in this case involves
  reducing the size of this FAT32 partition, creating a second partition
  in the new space, and formatting this second partition using an ext4
  filesystem.
* Frequent writes of large OS images can reduce the lifetime of the local
  storage (this is especially true for non-industrial-grade SD cards!).

