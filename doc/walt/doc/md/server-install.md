
# WalT server installation

## Overview

We provide instructions to setup walt server software and dependencies on a fresh (and minimal)
installation of debian 12 (bookworm) operating system.

Note that walt server software starts various network daemons (lldpd, snmpd, dhcpd, ptpd, ntpd,
tftpd, nfsd), thus you should not run other software related to network management on this walt
server machine.
You should also avoid installing a desktop environment (e.g. Gnome) on this machine, as this
will probably try to "setup" network interfaces when loading and interfere with WALT.
Use SSH instead.


## Hardware requirements

The WalT server must be installed on a 64bits (intel / amd64 CPU) machine, equipped with the following:
* A 64 bits (intel or amd) CPU (recent core i5 or better is recommended).
* A 250Go (or more) disk.
* 16 Go RAM or more is recommended (RAM is mainly needed for the "virtual nodes" feature).
* 2 wired LAN interfaces (recommended).

Note: one may use a USB-ethernet dongle as an alternative to the second LAN interface.
See [`walt help show networking`](networking.md) and [`walt help show server-network-config`](server-network-config.md).

WalT is often used in one of the following scenarios:
* Standard deployment in a building
* Mobile setup (for demos)

In the first case, you could install WalT on a server in the datacenter of the building.
In the second case, you could choose a small-form-factor PC.
Contact us (walt-contact at univ-grenoble-alpes.fr) for more advice.


## 1- Install and configure walt software

Run this as `root` user:

```text
~# apt update; apt install -y gcc python3-venv python3-dev libsmi2-dev
~# python3 -m venv /opt/walt-10.0
~# /opt/walt-10.0/bin/pip install --upgrade pip
~# /opt/walt-10.0/bin/pip install walt-server walt-client
~# /opt/walt-10.0/bin/walt-server-setup
```

Note: `walt-server-setup` will display interactive configuration interfaces for network, image registries, and VPN.

For more information:
* About WalT network concepts and configuration, see [`walt help show networking`](networking.md).
* About WalT image registries, see [`walt help show registries`](registries.md).
* About WalT VPN and distant nodes, see [`walt help show vpn`](vpn.md).


## 2- Log in as a different user

For simplicity, we may stay on the WALT server machine and use the `walt` client software installed there. All OS users can use this client software, including `root`, but using a different user is obviously recommended.

When you installed the Debian OS, the installer prompted for a (non-root) username, so you can use this one. Or you can use `adduser <username>` to create a new user. The server machine may also be configured with an external database of users (e.g., LDAP), but this OS configuration is beyond the scope of WALT.

For logging in with this user, open another ssh session or type `su - <username>` from the root shell.

Note: it is also possible to install and use the client software on another machine. See [`walt help show client-install`](client-install.md) for more info.


## 3- Start playing!

The system is now all set.
You can first verify that the system is running well by creating a virtual node.
```
$ walt node create vnode1
$ walt node shell vnode1
```

Note: WalT will detect that you are a new user and ask you for some configuration settings.

After a few minutes (download of the default image + node bootup) you should be connected on the virtual node.

Then, connect a switch, physical nodes and check that you can reach them (see [`walt help show node-install`](node-install.md)).
Caution: do not connect a node directly to the server (with no intermediate switch). It will NOT work.
(See [`walt help show networking`](networking.md) and [`walt help show switch-install`](switch-install.md).)

