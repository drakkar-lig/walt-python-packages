# Building a WalT image from a Dockerfile

In order to modify an image easily, one can use `walt image shell` or `walt image cp`.
However, listing build steps in a [Dockerfile](https://docs.docker.com/engine/reference/builder) makes an image build reproducible, a valuable feature for image maintenance.
Command `walt image build` allows to build images this way.


## Using `walt image build`

This command has two modes of operation:
* option `--from-url` allows to specify the URL of a git repository (e.g., on github)
* option `--from-dir` allows to specify a local directory on the client.

In both cases, a Dockerfile must be present at the root of the specified repository or directory.
The other files contained in the repository or directory may be used in ADD and COPY instructions.

As a last command argument, one has to specify the name of the resulting image.
If this name is already in use, the previous image will be overwritten (after a confirmation prompt).


## Build tips

Most users use the default images as a starting point, in order to inherit provided features
and image compliance with the walt system.
Default images are named `waltplatform/<node-model>-default:latest`.
For instance, the default image for `rpi-b-plus` nodes is `waltplatform/rpi-b-plus-default:latest`.

Here is a sample Dockerfile adding `tshark` to this default image:

```
FROM waltplatform/rpi-b-plus-default:latest
RUN apt update && apt install -y tshark
```

In some very specific cases, one may also create the image completely from scratch.
However, in this case, the user must ensure the resulting image complies with walt image requirements.
For details, see [`walt help show image-from-scratch`](image-from-scratch.md).


## Alternative methods

Users may also build walt images by just using docker tooling, and then importing them into walt internal registry.


### Using the docker hub

The image can be built on any build machine equipped with docker:

```
$ docker build -t <user>/<image-name> .     # build
[...]
$ docker push <user>/<image-name>           # publish on the docker hub
[...]
$
```

And then it can be retrieved by using the walt client:

```
$ walt advanced rescan-hub-account          # let walt know about the new remote image
[...]
$ walt image search <image-name>            # verify walt can find it
[...]
$ walt image clone hub:<user>/<image-name>  # import into walt
[...]
```


### Working on the walt server

When working on the walt server, which is equipped with docker tooling, the workflow is even simpler:

```
$ docker build -t <user>/<image-name> .         # build the image
[...]
$ walt image search <image-name>                # walt should detect it on the docker daemon
[...]
$ walt image clone docker:<user>/<image-name>   # import into walt
[...]
```


