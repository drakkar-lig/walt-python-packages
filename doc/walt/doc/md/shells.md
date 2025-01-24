
# Shell usage notes

## Introduction

WalT users can use the following kinds of shell sessions:
* `walt node shell`
* `walt image shell`


Their purpose is very different.


## `walt node shell`: access to the real node

`walt node shell` just wraps a ssh session to the node.

Warning: in the default boot mode, a WalT node is a very **volatile**
environment. Each time a node reboots, it loses all modifications made
on files (created, suppressed, modified), and restarts from the original
files of the OS image it boots.
This ensures that a node booting a given image will always act the same.
(See [`walt help show node-bootup`](node-bootup.md) for a more technical
explanation on this aspect.)

However, for convenience, a directory `/persist` is available on each node.
Data stored there do remain available accross reboots. You can use it to
store large experiment results files for instance.
`/persist` is a read-write NFS-mount: data is actually stored on the server.

For more specific needs, you may also consider the hybrid-persistent boot
mode (see [`walt help show boot-modes`](boot-modes.md)) to make the whole OS
persistent.



## `walt image shell`: modification of operating system

In order to automate a given test or experience, you must modify the OS
images the nodes will boot. `walt image shell` is one easy way
to do this. It provides a shell running in a virtual environment (docker
container) where you can make the changes, for example install packages and
automate the startup of your experiment script at bootup (using `cron`, or
a `systemd` unit, etc.).


### The virtual environment provided by `walt image shell`

Some of the images allow starting the OS init in the virtual environment,
making the shell session ressemble the experience of `walt node shell`.
For instance, we see here that various OS services were automatically
started in the background:
```console
$ walt image shell pc-x86-64-default
Note: the OS was started in a virtual environment.
Run 'walt help show shells' for more info.

root@image-shell:~# ps -ef
UID      PID PPID  C STIME TTY       TIME CMD
root       1    0  1 12:05 ?     00:00:00 /sbin/init
root       7    0  0 12:05 pts/0 00:00:00 /bin/bash
root      22    1  0 12:05 ?     00:00:00 /lib/systemd/systemd-journald
_rpc      48    1  0 12:05 ?     00:00:00 /sbin/rpcbind -f -w
avahi     52    1  0 12:05 ?     00:00:00 avahi-daemon: running [image-shell.local]
root      53    1  0 12:05 ?     00:00:00 /usr/sbin/cron -f
message+  54    1  0 12:05 ?     00:00:00 /usr/bin/dbus-daemon --system [...]
root      56    1  0 12:05 ?     00:00:00 lldpd: monitor.
root      60    1  0 12:05 ?     00:00:00 /lib/systemd/systemd-logind
_lldpd    64   56  0 12:05 ?     00:00:00 lldpd: no neighbor.
avahi     65   52  0 12:05 ?     00:00:00 avahi-daemon: chroot helper
root      70    1  0 12:05 ?     00:00:00 sshd: /usr/sbin/sshd -D [...]
root      91    7  0 12:05 pts/0 00:00:00 ps -ef
root@image-shell:~#
```

Other more minimalist images may not provide such feature, so the virtual
environment is started with just the shell process itself:
```console
$ walt image shell pc-x86-64-openwrt
Note: this is a limited virtual environment (with just the shell process).
Run 'walt help show shells' for more info.

BusyBox v1.33.2 (2022-04-16 12:59:34 UTC) built-in shell (ash)

~ # ps -ef
  PID USER       VSZ STAT COMMAND
    1 root      1108 S    /bin/sh
    7 root      1104 R    ps -ef
~ #
```

In the first case, the user can easily install and configure complex tooling,
for instance install the `postgresql-server` package, then connect to the
new postgresql service, start a `psql` command, and initialize a database
relevant for the experiment.

In the second case, doing the same is hard because there is no OS tooling
ready to start and manage the postgresql service once it is installed.
In this case, one may resort to:
- do the changes directly on the node and then save the modified OS using
  `walt node save`; see [`walt help show node-save`](node-save.md).
- or automate a part of this setup procedure at node bootup
- or use the hybrid-persistent boot mode (cf. [`walt help show boot-modes`](boot-modes.md)).

Actually, even if the image supports starting the OS, `walt image shell`
still runs in a container, which may be a problem in some cases.
For instance, you may want to run a complex installation procedure you
did not write yourself, and this procedure may contain actions not allowed
in a container (e.g., modify the OS firewall rules). In this case,
using `walt node save` or one of the other alternatives listed above can
probably help you.

Note that advanced virtual environments (as in the 1st case above) are only
available with an up-to-date WALT server (cf. [`walt help show server-upgrade`](server-upgrade.md)),
and also require related support on the WALT image itself. The default image
of Raspberry Pis and the one of PC nodes (which is the default of virtual
nodes too) now provide this support.
You can find these updated images by typing `walt image search waltplatform`
and then use `walt image clone` to get them. You may also let the server
update these default images in its internal repository by running
`walt advanced update-default-images` (cf. [`walt help show node-ownership`](node-ownership.md)),
so that new users, newly created virtual nodes and newly detected physical
nodes get those updated OS images by default.

If you are using an older version of those images, or an older WALT platform,
then only a basic virtual environment is provided with `walt image shell`.

Note: if ever you need it, you can learn how to support advanced virtual
environments in an image lacking this support by typing
[`walt help show image-from-scratch`](image-from-scratch.md)).


### Notes on CPU emulation

Since the image is expected to be booted by a node, and the CPU architecture
of the node may be different from the one of the server (e.g. ARM-based
raspberry pi versus amd64-based server), the binaries found inside an image
may not be compatible with the server CPU. In this case, any binary you run
in this shell will involve **CPU emulation**, leading to a slower behavior.


### Alternate commands to modify a WALT image

The other options to modify an OS image are:
* `walt image cp`: add a file or directory to a given image. See [`walt help show image-cp`](image-cp.md).
* `walt image build`: build an image by using a Dockerfile. See [`walt help show image-build`](image-build.md).
* `walt node save`: save OS modifications you have done directly on a node to a new WalT image.
  See [`walt help show node-save`](node-save.md).


## Summary table

The following table summarizes usage of these 2 commands and their limits.

|                 | walt node shell            | walt image shell                            |
|-----------------|----------------------------|---------------------------------------------|
| persistence     | until the node reboots (1) | yes                                         |
| backend         | the real node              | virtual environment, possible CPU emulation |
| target workflow | testing/debugging          | apply changes                               |

(1): unless using the hybrid-persistent mode (cf. [`walt help show boot-modes`](boot-modes.md)).
