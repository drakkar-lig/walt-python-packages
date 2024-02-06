
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


## Relation with OS images

A "free" node is a node that boots its default image.
Thus, command `walt node release <node(s)>` is actually the same as `walt node boot <node(s)> default`.

The default image of a node is an image stored in walt internal repository with the name `waltplatform/<node-model>-default`.
When a new model of node is connected to the platform, the default image is downloaded [from the docker hub](https://hub.docker.com/u/waltplatform)
in the background and associated to the new node.

A node belonging to a given user is a node that boots one of the images of that user.
Thus, `walt node acquire <node(s)>` is actually the same as:
```
$ walt image clone walt:waltplatform/<node-model>-default  # I get my own clone of the default image
$ walt node boot <node(s)> <node-model>-default            # I associate nodes to my new image
```
For clarity regarding images supporting several node models, `walt node acquire` sometimes gives a different name to the cloned image (not `<node-model>-default`).
This name is obviously printed.

New users automatically get a clone of the default images present on the platform, the first time they type `walt image show`.
It is possible to update the default images present on the platform using `walt advanced update-default-images`. This command will look for newer
default images on remote registries (docker hub and/or any private registry configured) and will also query the docker daemon running on the WALT server.
