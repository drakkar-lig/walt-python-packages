
# Transfering files to or from a node

`walt node cp` allows to transfer files to or from a node.
Its interface is very similar to `scp`, but simplified. Three forms are allowed:
```
$ walt node cp <node>:<path> <local-path>
$ walt node cp <local-path> <node>:<path>
$ walt node cp <node>:<path> booted-image
```

The first two forms are obvious. Note that you can transfer files or directories the same way (no specific option is needed for directories).

The last form allows to simplify a usual workflow of walt users. This workflow is the following:
1. in a first phase, while debugging, one usually connects directly to a node, and updates files there
2. then, in order to make those changes persistent when node will reboot, they must be retrieved and applied to the walt image

Without this third form, users would have to use `walt node cp` to retrieve modified files and make a local copy (on client computer), then `walt image cp` (see [`walt help show image-cp`](image-cp.md)) to transfer again those files from client computer to the image.

Using keyword `booted-image` allows to transfer files directly from the node to the image it has booted.
Note that this update of the image will trigger a reboot of this node once the transfer is done. It will also reboot any other node which has booted the same image.
