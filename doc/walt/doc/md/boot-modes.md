
# Boot modes: network boot and hybrid boot

## Introduction

**In its default mode of operation, WalT nodes boot over the network.**
This has several pros, described below. However, for some experiments, this mode may not be applicable.
In this case, users can fallback to one of the hybrid boot variants.


## Network boot mode

In a network booting scenario, the OS is stored on a remote server and is never transfered as a whole to the
node(s). Instead, the node sends network requests to the server each time it needs to access a file or directory.
In a sense, compared to booting on a local disk, network booting just means using the network controller
to read OS files and metadata instead of the disk controller.

In the case of a WalT node, the remote WalT image files and metadata are accessed in read-only mode.
In its bootup procedure, the node stacks on top of this remote layer an "overlay" layer implementing
copy-on-write semantics and using the RAM for storing modifications. This allows the OS (or the WalT user)
to create, modify or delete files even if the remote OS image is accessed in read-only mode.

This setup has the following pros:
* **Near-zero OS deployment delay.** Instead of transfering a whole image OS from the server to the node's disk,
  as most other platforms do, the server just updates a symlink to target the proper OS image and reboots
  the node. One could argue that network transfers happen once the node is booting instead, but the method
  remains very frugal on network resources: only the files and metadata that are actually necessary are
  transferred, which is typically less than 10% of the total OS image size.
* **Reproducibility ensured at each reboot.** Since the modifications are stored using an overlay in RAM,
  their are cleared when the node reboot, and the node restarts using exactly the same OS files, i.e.,
  those of the read-only remote WalT image.
* **Reduced platform maintenance burden.** The local disks or SD cards of the nodes are usually the most fragile
  components of a platform, so avoiding their use is preferable.

The main disadvantage of this network boot method is the limited storage space on RAM. The following
actions can be taken to avoid problems:
* **Heavy operations on files should be prepared in the walt image** (e.g, using `walt image shell`),
  not run once the node is booted.
* **Large experiment result files should be generated in the directory `/persist` of the node**. This
  directory is excluded from the RAM overlay setup; instead, it is a read-write NFS share, so files stored
  there are actually stored on the server, and they are preserved accross node reboots.

Sometimes, one may use the local disk(s) of a node as storage for a part of the experiment, and let the
network boot mode manage the OS files. It is easy to add local disks to virtual nodes (see
[`walt help show vnode-disks`](vnode-disks.md) for more info).

However, having the OS stored remotely may not match every possible experiment.
The alternate mode described below was designed to overcome this limitation.


## Hybrid boot mode

The hybrid boot mode allows to let the node copy the image contents on its local storage and then
boot from it.

Whatever the boot mode, the procedure is always network-based at first (i.e. targetting the
proper WalT OS image, and then downloading and running the kernel this image contains).
But then, walt-init scripts look for local disks (or SD cards) and ext4-formatted partitions.
If a directory named `walt-hybrid` is found in the root directory of one of these partitions,
the hybrid boot mode is enabled. Otherwise, the network boot mode continues.

Two hybrid mode variants exist: **volatile** and **persistent**.

Similarly to the network boot, the **volatile** variant properly ensures reproducibility at each
reboot. The copy of image contents on the local disk is kept read-only and another sub-directory
(of the same disk) is used as a read-write overlay. This overlay directory is reset at each bootup,
which leads to a clean boot, free of any artefact from the previous runs, and using only the WalT
image contents at first.

The **persistent** variant behaves differently: all file modifications are preserved accross
reboots. Thus reproducibility at each reboot is **not** ensured in this case. Actually, some
experiments involve a long preparatory phase of the OS files that cannot be done on the image
itself (e.g., using `walt image shell`), for whatever reasons. This **persistent** mode may be
handy in this case because this preparatory work will not be lost when the node reboots.

One can activate the **volatile** hybrid boot on a physical node by creating a directory named
`walt-hybrid` at the root of an ext4 partition, on a local disk (or SD card) of the node.
If an empty file named `.persistent` is created in this directory `walt-hybrid`, the boot method
switches to the **persistent** variant.

Using virtual nodes, one just has to select the appropriate template when adding the disk.
(See [`walt help show vnode-disks`](vnode-disks.md) for more info.)

Important notes:
* The first time a node boots an image in hybrid mode, the bootup time will be longer
  (up to several minutes longer, depending on network, disk, and image size) because of the
  complete copy of the WalT image to the local disk.
* The default partitionning of SD cards usually involves a single FAT32 partition. Activating the
  hybrid mode in this case involves reducing the size of this FAT32 partition, creating a second
  partition in the new space, formatting this second partition using an ext4 filesystem, and
  creating the `walt-hybrid` directory.
* Frequent writes of large OS images can reduce the lifetime of the local storage (this is
  especially true for non-industrial-grade SD cards!).
