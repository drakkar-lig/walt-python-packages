
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

If you want to use our provided server OS image, see [`walt help show server-install-from-image`](server-install-from-image.md).
If you prefer to use a machine already installed with debian OS, see [`walt help show server-install-from-fresh-debian`](server-install-from-fresh-debian.md).


