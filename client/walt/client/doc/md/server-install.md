
# How to install a WalT server

## Overview

These instructions assume you are familiar with Debian operating systems.

For easy setup, we provide a server OS image at https://github.com/drakkar-lig/walt-project/releases/latest.
When dumped to a USB flash drive, you can use it to boot any PC and turn it into a WalT server.
Then, you can migrate the OS to the internal disk of the server.

Alternatively, we provide instructions to setup walt server software and dependencies on a freshly installed
debian system.

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

About the USB flash drive: 16Go can be enough, considering you will migrate to the server main disk soon
(see below).


## Installing the walt server system

If you want to use our provided server OS image, see [`walt help show server-setup-from-image`](server-setup-from-image.md).
If you prefer to use a machine already installed with debian OS, see [`walt help show server-setup-from-fresh-debian`](server-setup-from-fresh-debian.md).


## Configuring the network on the server

See [`walt help show server-network-config`](server-network-config.md).
Once the network is configured, **reboot the server**.
When started, verify that network configuration was applied as you wish.


## Starting walt service

In the testing phase, you can just start walt server process manually, by typing
`walt-server-daemon`. This allows to show debug logs without having to use systemd journal.
Type ctrl-C to stop it.

Once everything is setup (network conf, etc.) and working, you can let systemd start `walt-server-daemon` itself:
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
Then, start `walt` tool and answer questions:
```
$ walt
Starting configuration procedure...
ip or hostname of WalT server: localhost
Docker hub credentials are missing, incomplete or invalid.
(Please get an account at hub.docker.com if not done yet.)
username: <docker-hub-user>
password: <docker-hub-password>

Configuration was stored in /root/.waltrc.

Resuming normal operations...
[...]
```

Now, we can test that the system is running well by creating a virtual node.
```
$ walt node create vnode1
$ walt node shell vnode1
```

After a few minutes (download of the default image + node bootup) you should be connected on the virtual node.

Then, connect physical nodes and check that you can reach them (see [`walt help show node-install`](node-install.md)).
Caution: do not connect a node directly to the server (with no intermediate switch). It will NOT work.
(See [`walt help show networking`](networking.md) and [`walt help show switch-install`](switch-install.md).)


## Optional final step

If you chose the setup based on the USB image, you probably want to migrate the OS from the USB device to the main disk
of your system. See [`walt help show server-setup-from-image`](server-setup-from-image.md) for details.

Your WALT server is now installed and ready to help with your experiments.

