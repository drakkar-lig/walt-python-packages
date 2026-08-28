
# Default OS images

For each node model WALT supports, there exists a default OS image.
This image is owned by fictitious user `waltplatform`: `waltplatform/<node-model>-default`.

When a new model of node is connected to the platform, the default image is downloaded [from the docker hub](https://hub.docker.com/u/waltplatform)
in the background. Since WALT cannot know which user connected this node, it is considered "free" at first (until someone "acquires" it). So the default image is duplicated as `waltplatform/<node-model>-free` and associated to the new node.
All future free nodes of this model will also boot this image, unless command `walt advanced set-free-nodes-image` is used.
See [`walt help show node-ownership`](node-ownership.md) for more information.

New users automatically get a clone of the default images present on the platform, the first time they type `walt image show`.
For clarity regarding images supporting several node models, the name given to these default images is sometimes different (i.e., not `<model>-default`). For instance, if there are `rpi-3-b-plus` and `rpi-4-b` models on the platform, the user may obtain a single OS image named `rpi64-default` and compatible with both models.

It is possible to update the default images present on the platform using `walt advanced update-default-images`. This command will look for newer
default images on remote registries (docker hub and/or any private registry configured) and will also query the docker daemon running on the WALT server.
