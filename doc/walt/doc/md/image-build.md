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


## Diverting Dockerfile RUN commands to a real node

Sometimes, a setup procedure may have been tested successfully on a real machine
but fail to run properly as a RUN command in the Dockerfile.

For instance, let's consider the following Dockerfile:
```
FROM waltplatform/pc-x86-64-default
RUN apt update && apt install -y sudo postgresql
COPY backup.sql /root/
RUN sudo -u postgres psql < /root/backup.sql
```

Unfortunately, building this Dockerfile fails at the last step:
```
$ walt image build --from-dir . dbimage
[...]
STEP 4/4: RUN sudo -u postgres psql < /root/backup.sql
psql: error: connection to server failed [...]
      Is the server running locally [...]?
[...]
$
```

Note that you would get the same failure with a plain `docker build` or
`podman build`, this problem is not specific to `walt`.

In fact, each RUN command is executed successively within its own "Linux container" -- a virtual
and restricted environnement created on-the-fly on the WALT server.
In this example, the postgresql client `psql` tries to connect to its server
to populate the database with a backup. But in this minimal environment, the
operating system is not started, so even if the postgresql server was properly
installed by `apt` at step 2, it has never been started.

Unless appropriate measures described below are taken, several kinds of commands
will fail in a Dockerfile too:
* commands supposed to work once the OS is running, such as `psql` in our example;
* commands which require special privileges not allowed in a "Linux container";
* commands specifically designed to work on a real machine, not as a step
  of an OS image build procedure (e.g., a script trying to probe the model of
  a peripheral device supposedly connected to the machine).

Since v11, WALT offers an easy way to solve this problem: one can divert one
or more `RUN` commands to a WALT node during the build of a Dockerfile.
This requires two things:
* Adding option `--with-node <node>` on `walt image build` command line.
* Replacing failing `RUN` directives of the Dockerfile by `RUN --on-node`.

So we can easily fix our example:
```
$ walt image build --from-dir . --with-node pc2-426 dbimage
[...]
STEP 4/4: RUN --on-node sudo -u postgres psql < /root/backup.sql
Preparing intermediate image for node bootup...
Rebooting pc2-426 on the intermediate image...
Waiting for pc2-426 to be booted...
Running the command on pc2-426...
CREATE ROLE
CREATE DATABASE
[...]
Successfully tagged docker.io/eduble/dbimage:latest
```

This time, the image was built properly.

Note that for each `RUN --on-node` step, WALT has to:
1. Boot the node on the intermediate OS image made of the previous
   Dockerfile build steps.
2. Run the specified command on the node.
3. Save file changes made on the node as a new layer of the OS image
   being built.

This is significantly slower than a regular `RUN` command,
so you are advised to use `RUN --on-node` only where a regular `RUN` fails.


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
