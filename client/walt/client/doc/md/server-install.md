
# WalT server installation

## Overview

We provide instructions to setup walt server software and dependencies on a freshly installed
debian 11 (bullseye) operating system.

Note that walt server software interacts with various network daemons (lldpd, snmpd, dhcpd, ptpd, ntpd,
tftpd, nfsd), thus you should not run other software related to network management on this walt server
machine.


## Hardware requirements

The WalT server must be installed on a 64bits (intel / amd64 CPU) machine, equipped with the following:
* A 64 bits (intel or amd) CPU (recent core i5 or better is recommended).
* A 250Go (or more) disk.
* 16 Go RAM or more is recommended (RAM is mainly needed for the "virtual nodes" feature).
* 2 wired LAN interfaces (recommended).

Note: in some cases, 1 wired network interface may be enough with appropriate configuration of the
server and/or network equipment. See section about network configuration.

WalT is often used in one of the following scenarios:
* Standard deployment in a building
* Mobile setup (for demos)

In the first case, you could install WalT on a server in the datacenter of the building.
In the second case, you could choose a small-form-factor PC. These rarely provide 2 LAN interfaces, but a
few models do; and most of them are barebone (you need to buy RAM and disk separately).
Contact us (walt-contact at univ-grenoble-alpes.fr) for more advice.


## 1- Install a first set of packages

```
$ apt update
$ apt install -y gcc python3-venv python3-dev libsmi2-dev curl git make
```

## 2- Install and configure walt software

Here you have two options:
- Install the last official version of walt (recommended)
- Install the development version of walt (with last features and access to source code versioning,
  but less thoroughly tested)

If you want the official version:
```
$ python3 -m venv /opt/walt-8
$ /opt/walt-8/bin/pip install walt-server walt-client
$ /opt/walt-8/bin/walt-server-setup
```

If you want to setup the development version instead:
```
$ cd /root
$ git clone https://github.com/drakkar-lig/walt-python-packages
$ cd walt-python-packages
$ git checkout -b dev origin/dev
$ make install
```

Note: in any case, interactive configuration interfaces for network and image registries will be displayed.
For more information about WalT network concepts and configuration, see [`walt help show networking`](networking.md).
For more information about WalT image registries, see [`walt help show registries`](registries.md).


## 3- Start playing!

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

