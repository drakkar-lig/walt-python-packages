
# Node ownership

The concept of node ownership implemented in WalT helps users to share platform resources when using the platform at the same time.
As shown below, the platform usage remains very flexible (see [`walt help show design-notes`](design-notes.md) for related concepts).


## "Acquiring" and "Releasing" nodes

A node is considered to be used by 0 or 1 user at a given time. If 0, the node appears as "free". If 1, we consider that this user **owns** the node.
Users can get or release ownership of a (set of) node(s) by using commands `walt node acquire <node(s)>` and `walt node release <node(s)>`.

When running `walt node show` with no option, only the nodes one owns are listed.
When running `walt node show --all`, free ones and those of other users are listed too.

After a node is released, it appears as "free" for all users.
At the end of an experiment, a good practice is to release all the nodes one owns:
```
$ walt node release my-nodes
```
(`my-nodes` is a keyword, cf. [`walt help show device-sets`](device-sets.md) for details.)

Releasing PoE-powered nodes also allows automatic power savings (cf. [`walt help show optional-features`](optional-features.md)).

Users usually acquire nodes from the set of "free" ones. However, a teammate may have forgotten to release some nodes.
In this case, one can still acquire such nodes owned by someone else but a confirmation is required.


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

For instance `walt advanced set-free-nodes-image rpi-3-b-plus rpi-standby` clones my image `rpi-standby` under the name `waltplatform/<node-model>-free` and reboots all free rpi 3B+ nodes. Moreover, from now on, each time a user releases a rpi 3B+ node it will also boot this image.

The `set-free-nodes-image` command is often used to enable free nodes to host a discovery service—such as the detection of connected USB devices—so that users know which nodes to acquire for a specific experiment.
