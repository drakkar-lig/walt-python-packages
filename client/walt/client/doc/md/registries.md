
# WalT image registries

## Overview

Image registries allow to share WalT images, a major feature for reproducibility and/or
team working.

The following is a list of image registries walt can use.


## WalT internal repository

The WalT server internally manages the images by using `podman`, `buildah` and `skopeo`
tools.

When using `walt image search`, WalT will list images of this internal repository,
with a clone URL starting with `walt:`.
However, it will only list images belonging to other users, since images belonging
to the calling user are those printed when typing `walt image show`.
It is therefore obvious to import images built by teammates into one's own working set
by using `walt image clone <url>`.


## Docker Hub

In their default configuration, WalT servers are configured to publish and clone images
to/from the docker hub at [hub.docker.com](https://hub.docker.com/).

The WalT development team publishes default images for various kinds of WalT nodes there:
* `waltplatform/rpi-*-default:latest`: default images for various Raspberry Pi models
* `waltplatform/pc-x86-64-default:latest`: default image for 64-bit PCs
* `waltplatform/pc-x86-32-default:latest`: default image for 32-bit PCs

When using `walt image search`, WalT will list these remote images with a clone URL starting
with `hub:`, and this clone URL can be used to download them using `walt image clone <url>`.

The command `walt image publish` can be used to publish images on the Docker Hub.
Referencing the resulting clone URL in a research paper can help reproducibility.

Since the Docker Hub is a public registry, its use may not match all needs (e.g., a private
company may not want to publish images involving industrial secrets).
It is possible to reconfigure WalT to use a local registry instead of the Docker Hub,
or to use both the Docker Hub and a local registry, as described next.


## Docker local registry

As an alternative to the Docker Hub, one can install its own docker image registry by using
the [documented procedure](https://docs.docker.com/registry/deploying/).

Basically, running this command on a machine equipped with the `docker` engine is enough:
```
[registry-machine]$ docker run -d -p 5000:5000 --restart=always --name registry registry:2
```

Host `registry-machine` now has an image registry server listening on port 5000.

WalT can be reconfigured to use this registry server by using:
```
root@walt-server:~$ walt-server-setup --edit-conf
```

A network configuration editor will be displayed first, and the configuration editor
for registries next. Using this configuration editor to declare the new registry server
available on `registry-machine` should be obvious.

Using this configuration editor, one might also disable the Docker Hub, but it is not
recommended, because of the default images stored there.
The first time a new kind of node is detected, WalT has to download a default image
for it. This image can usually be found on the Docker Hub, but WalT will also
try the local registry if any. If all fails, then the WalT server will not be able to
manage this new node.
As a consequence, disabling the Docker Hub should only be done after all needed default
images are downloaded (at least one node of each kind could boot at least once), and
keeping in mind that the WalT server will not be able to manage new kinds of nodes in
the future, unless a default image is made available for them in the local registry.

When configuring a local registry, a label should be given on the editor interface.
This label is then used in the clone URL of `walt image search`, `walt image clone`,
and possibly for the `--registry` option of `walt image publish`.
For instance, if the label "local" is chosen, then clone URLs of images stored in
the local registry will be prefixed with `local:`, and one can use
`walt image publish --registry local <image-name>` to upload an image into this
local registry.


## Docker daemon on walt server

Many WalT users create their images in an incremental way, by using various `walt image shell`
or `walt image cp` steps.

However, for better reproducibility and self-documentation, it is also possible to generate
a WalT image from a Dockerfile.
For instance:

```
FROM waltplatform/pc-x86-64-default:latest
RUN apt install -y ...
[...]
```

And then create the image with `walt image build`.
See [`walt help show image-build`](image-build.md).


Since the WalT server is also equipped with the docker command, users
can also use a plain `docker build` there to create an image.
Non-root users must be added to the `docker` group beforehand.
In this case the resulting image will be owned by the `docker` daemon, not directly by WalT.
When using `walt image search`, WalT will indicate a clone URL starting with `docker:`,
and then using `walt image clone <url>` it is easy to import it into WalT internal repository.
