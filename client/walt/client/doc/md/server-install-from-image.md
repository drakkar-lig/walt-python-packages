
# Walt server setup from USB image

## Overview

These are the steps you should follow to install a walt server machine using the USB image we provide.


## 1- Boot the machine using WalT server image

* Download the OS image `server-install-prod.dd.bz2` from https://github.com/drakkar-lig/walt-project/releases/latest.
* Uncompress and dump it to your USB drive (assuming a linux-based machine, and your USB disk at `/dev/sdX`):
  `$ bzcat server-install-prod.dd.bz2 | dd of=/dev/sdX bs=10M; sync; sync`
* Boot the server machine using the flash drive (by configuring BIOS/UEFI boot settings accordingly).
* When asked, enter the root OS password you want to set on this server.
* When OS is booted, you can login with user `root` and the password you just specified.


## 2- Move to the main disk

Over time, a walt server needs more disk space to store walt images.
So you probably want to migrate the server operating system from the USB flash drive to the server's internal disk.

This can actually be done at any time by running the following script:
```
$ /opt/debootstick/live/init/migrate-to-disk.sh
```

The procedure is completely transparent: the system will continue working so
you can continue this procedure while it runs.
When done, you can remove the USB flash drive (no need to reboot).

Note: the OS is moved, not copied. Thus the USB flash drive cannot be used right away to
install another server. You should flash it again in this case.


## 3- (Optional but recommended) Update configuration

In its default configuration, the server has a virtual-only configuration:
it will only manage virtual nodes.

In order to configure it to accept physical nodes, type the following command.
An interactive configuration interface will be displayed.
Note that you can pass this step for now, start playing with the virtual-only setup,
and run this command later.

```
$ walt-server-setup --edit-conf
```

For more information about WalT network concepts and configuration, see [`walt help show networking`](networking.md).


## 4- Configure docker hub credentials

In order to be able to use `walt` command line tool, you need valid docker hub credentials.
If you do not have such an account yet, register at https://hub.docker.com/signup.
Then, start `walt` tool and answer questions:
```
$ walt
Starting configuration procedure...
ip or hostname of WalT server: localhost
Docker hub credentials are missing, incomplete or invalid.
(Please get an account at hub.docker.com if not done yet.)
username: <docker-hub-user>
password: <docker-hub-password>

Configuration was stored in /root/.walt/config.

Resuming normal operations...
[...]
```

## 5- Start playing!

The system is now all set.
You can first verify that the system is running well by creating a virtual node.
```
$ walt node create vnode1
$ walt node shell vnode1
```

After a few minutes (download of the default image + node bootup) you should be connected on the virtual node.

Then, connect physical nodes and check that you can reach them (see [`walt help show node-install`](node-install.md)).
Caution: do not connect a node directly to the server (with no intermediate switch). It will NOT work.
(See [`walt help show networking`](networking.md) and [`walt help show switch-install`](switch-install.md).)

