
# Specifics of free nodes

## What is a free node?

See [`walt help show node-ownership`](node-ownership.md).


## The OS image of free nodes

A "free" node boots a special OS image owned by fictitious user `waltplatform`: `waltplatform/<node-model>-free`.
At first, this OS image is a clone of the default image for this node model.
See [`walt help show default-images`](default-images.md) for more information about default OS images.

It is possible to let free nodes boot a different image by using the following command:
```
$ walt advanced set-free-nodes-image <node-model> <image-name>
```

Here `<image-name>` is either one of your images (as listed by `walt image show`), or the keyword `default`.
Keyword `default` allows to revert the image of free nodes to their default image.
Since a given image may be compatible with several node models, the `<node-model>` parameter allows to specify which one the command should apply to.

Use this command with caution: it applies to all current and future free nodes of the specified model, whoever releases a node.

For instance, `walt advanced set-free-nodes-image rpi-3-b-plus rpi-standby` clones my image `rpi-standby` under the name `waltplatform/<node-model>-free` and the reboots all rpi 3B+ nodes currently free. Moreover, from now on, each time a user releases a rpi 3B+ node it will also boot this image.

The `set-free-nodes-image` command is often used to enable free nodes to host a discovery service—such as the detection of connected USB devices—so that users know which nodes to acquire for a specific experiment.


## Free nodes and the powersave feature

Keep in mind that WALT may automatically power off unused free nodes, for power saving, by disabling their Power-over-ethernet supply after a delay. See [`walt help show powersave`](powersave.md) for tips about that.
