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

Modifying an OS image using `walt image shell` is sometimes challenging because this
command works in a "linux container" environment, not on a real node.
See [`walt help show shells`](shells.md) for more info.
Because of this, a small set of operations may not work or not be allowed.
In this case, making the changes directly on a node and then saving the OS image with
`walt node save` is a handy workaround.

If you want to make your image building procedure reproducible, you should
use `walt image build` instead of `walt node save` or `walt image shell`.
With `walt image build`, one can easily divert Dockerfile `RUN` commands to a real node
if facing this kind of problem. See [`walt help show image-build`](image-build.md) for more info.



## Tips and limits

Remember that nodes have their internet connectivity disabled by default.
See [`walt help show device-netsetup`](device-netsetup.md) if you need to
update this parameter while working on the node.

When the node is configured with the default boot mode, `network-volatile`,
it stores file changes in its RAM. As a result, heavy operations on files
(such as installation of OS packages) will probably cause the node to **swap**
or run out of RAM. One should run those heavy operations as a preliminary
OS setup phase instead, using `walt image build` or `walt image shell`,
and then let the node boot this prepared OS.
If for whatever reason this is not possible, one could also configure the
node with boot mode `network-persistent`, which stores file changes remotely
on the server with no size limit.
See [`walt help show boot-modes`](boot-modes.md) for more info.


## How the command works

First, the command retrieves the set of file modifications (created or modified files)
applied on the node.
Then the new image is built by applying this set of modifications on top of the
current WalT image which was booted by the node.

This command usually runs fast because WalT nodes store file modifications separately
from the content of the initial image. In the default boot mode for instance:
* The content of the initial image is accessed as a read-only NFS mount.
* The file modifications are stored in a RAM overlay.

Storing file modifications separately allows to implement a concept of
"reproducibility at each reboot". See [`walt help show node-reboot`](node-reboot.md) for more info.
