# Saving the current OS state of a node

`walt node save` allows to save the current OS state of a node as a new WalT image.

Its prototype is the following:
```
$ walt node save <node> <image-name>
```

You may either enter a new `<image-name>` or reuse the name of an image you want
to override.


## Purpose

Instead of modifying an OS image for a given experiment and then booting nodes with it,
this command allows to work the other way: do the modifications directly on a node,
and then save the current node state as a new WalT image.

Modifying an OS image using `walt image shell` or `walt image build` is sometimes
challenging because those commands work in a "linux container" environment, not on
a real node. See [`walt help show shells`](shells.md) for more info. Because of this, a small
set of operations may not work or not be allowed.
In this case, making the changes directly on a node and then saving the OS image with
`walt node save` is a handy workaround.


## Limits

This command is not able to detect files and directories which were **removed**
(comparing to the original OS image booted by the node); only files which were
**modified** or **created** are detected.
If you need to remove some files of an OS image, use `walt image shell` instead.

Heavy operations on files (such as installation of OS packages) should preferably
be done on the OS image, not directly on the node, because it will probably cause
the node to **swap** or run out of RAM. See [`walt help show boot-modes`](boot-modes.md) for
more info. If a part of your setup procedure uses `walt node save`, then it should
preferably be called with an image where those preliminary steps have already been
applied.


## How the command works

First, the command retrieves the set of file modifications (created or modified files)
applied on the node.
Then the new image is built by applying this set of modifications on top of the
current WalT image which was booted by the node.

This command usually runs fast because WalT nodes store file modifications separately
from the content of the initial image:
* The content of the initial image is accessed as a read-only NFS mount.
* The file modifications are stored in a RAM overlay.

The main reason for storing the overlay in RAM is to ease reproducibity. It ensures
the node discards all previous changes when it reboots, so it restarts with only the
content of the WalT image, unchanged.
To benefit from this "automatic cleanup", most WalT users reboot the nodes just before
each experiment run.
See [`walt help show boot-modes`](boot-modes.md) for more info about this overlay.
