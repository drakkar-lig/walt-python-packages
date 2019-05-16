
# How to install a WalT server

## Overview

These instructions assume you are familiar with Debian operating systems.
For easy setup, we provide a server OS image at https://github.com/drakkar-lig/walt-project/releases/latest.
When dumped to a USB flash drive, you can use it to boot any PC and turn it into a WalT server.
Then, you can migrate the OS to the internal disk of the server.

## Hardware requirements

The WalT server must be installed on a 64bits (intel / amd64 CPU) machine, equipped with the following:
* A 64 bits (intel or amd) CPU (recent core i5 or better is recommended).
* A 250Go (or more) disk.
* 16 Go RAM or more is recommended (RAM is mainly needed for the "virtual nodes" feature).
* 2 wired LAN interfaces.

Note: in some cases, 1 wired network interface may be enough with appropriate configuration of the
server and/or network equipment. See section about network configuration.

WalT is often used in one of the following scenarios:
* Standard deployment in a building
* Mobile setup (for demos)

In the first case, you could install WalT on a server in the datacenter of the building.
In the second case, you could choose a small-form-factor PC. These rarely provide 2 LAN interfaces, but a
few models do; and most of them are barebone (you need to buy RAM and disk separately).
Contact us (walt-contact at univ-grenoble-alpes.fr) for more advice.

About the USB flash drive: 8Go can be enough, considering you will migrate to the server main disk soon
(see below).

## Booting the machine using WalT server image

* Download the OS image `server-install.dd.bz2` from https://github.com/drakkar-lig/walt-project/releases/latest.
* Uncompress and dump it to your USB drive (assuming a linux-based machine, and your USB disk at `/dev/sdX`):
  `$ bzcat server-install.dd.bz2 | dd of=/dev/sdX bs=10M; sync; sync`
* Boot the server machine using the flash drive (by configuring BIOS/UEFI boot settings accordingly).
* When asked, enter the root OS password you want to set on this server.
* When OS is booted, you can login with user `root` and the password you just specified.

## Configuring the network on the server

See [`walt help show server-network-config`](server-network-config.md).
Once the network is configured, reboot the server.
On restart, make sure the server boots on the USB flash drive again.
When started, verify that network configuration was applied as you wish.

## Starting walt service

Once the network is setup and working, you can start walt service:
```
$ systemctl start walt-server
```

And have it automatically started on reboots:
```
$ systemctl enable walt-server
```

## Testing walt

The `walt` command line tool is installed on the server.

In order to be able to use it, you need valid docker hub credentials. If you do not have such an account
yet, register at https://hub.docker.com/signup.

Now, we can first test that the system is running well by creating a virtual node.
```
$ walt node create vnode1
$ walt node shell vnode1
```

After a few minutes (download of the default image + node bootup) you should be connected on the virtual node.

Then, connect physical nodes and check that you can reach them (see [`walt help show node-install`](node-install.md)).
Caution: do not connect a node directly to the server (with no intermediate switch). It will NOT work.
(See [`walt help show networking`](networking.md) and [`walt help show switch-install`](switch-install.md).)

## Move the OS to the main disk

Over time, a walt server needs more disk space to store walt images.
So you probably want to migrate the server operating system from the USB flash drive to the server's internal disk.

This can actually be done at any time by running the following script:
```
$ /opt/debootstick/live/init/migrate-to-disk.sh
```

The procedure is completely transparent: the system will continue working while it runs.
When done, you can remove the USB flash drive (no need to reboot).

Note: the OS is moved, not copied. Thus the USB flash drive cannot be used right away to
install another server. You should flash it again in this case.

## Concluding words

Your WALT server is now installed and ready to help with your experiments.

