# Building a WalT image from a Dockerfile

In order to modify an image easily, one can use `walt image shell` or `walt image cp`.
One can also do modifications directly on a node and then use `walt node save` to record the modified OS as a new image (see [`walt help show node-save`](node-save.md)).
However, listing build steps in a [Dockerfile](https://docs.docker.com/engine/reference/builder) makes an image build reproducible, a valuable feature for image maintenance.
Command `walt image build` allows to build images this way.


## Using `walt image build`

This command has two modes of operation:
* option `--from-url` allows to specify the URL of a git repository (e.g., on github)
* option `--from-dir` allows to specify a local directory on the client.

When using `--from-url`, one may use option `--sub-dir` to target a specific sub-directory
of the git repository to be used for the build. Otherwise the root directory is used.
In any case, a Dockerfile must be present in the target directory.
The other files contained in the target directory may be used in ADD and COPY instructions.

As a last command argument, one has to specify the name of the resulting image.
If this name is already in use, the previous image will be overwritten (after a confirmation prompt).


## Build tips: selection of the base image

The `FROM` line of the Dockerfile defines which existing image should be
used as a starting point. Building upon a WalT image allows to inherit provided features
and image compliance with the WalT system.

You should specify the `FROM` line like this:
```
FROM [<username>/]<image-name>[:<tag>]
```

If the `<tag>` part is omitted, tag `latest` is assumed. For instance `eduble/rpi-default` and `eduble/rpi-default:latest` are the same image. (All tools based on docker images work like this.)

If the `<username>` part is omitted, the username of the current user is assumed. For instance, if my username is `eduble`, then `FROM rpi-default` means `FROM eduble/rpi-default:latest`. This rule allows to directly reuse an `<image-name>` displayed by `walt image show`. Note that this is specific to `walt image build`: using a plain `docker build` instead, specifying the username would be mandatory.

Note: in case you want to write `<yourself>/<image-name>[:<tag>]` explicitely but forgot your `walt` username, check-out your client configuration file at `$HOME/.walt/config`.

As an alternative, you may want to specify user `<waltplatform>`, which is a kind of virtual user holding the default images of each node model.
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
