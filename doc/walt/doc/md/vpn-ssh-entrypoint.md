# How to setup a WalT VPN SSH entrypoint

## Introduction

Distant WalT nodes use a specific VPN boot procedure:
1. They download initial boot files (including a Linux kernel and an initial ramdisk) using HTTP requests to the VPN HTTP entrypoint and use them to boot;
2. While in the initial ramdisk code, they set up an SSH tunnel to the VPN SSH entrypoint and continue the boot procedure through that tunnel.

This documentation page explains how to set up the VPN SSH entrypoint mentioned in step 2.
For step 1, see [`walt help show vpn-http-entrypoint`](vpn-http-entrypoint.md) instead.
And for more background information, see [`walt help show vpn`](vpn.md) and [`walt help show vpn-security`](vpn-security.md).


## Purpose of the VPN SSH entrypoint

The VPN SSH entrypoint is just an SSH proxy which redirects to the WALT server.
Obviously, if you want to deploy distant WalT nodes anywhere on internet, this SSH proxy must be reachable from internet.


## Configuring a machine as a VPN SSH entrypoint

The machine must be equipped with an OpenSSH service and a few basic commands: `useradd`, `mkdir`, `cat`, `chmod`, `chown` and `ssh-keyscan`.

The configuration process is mostly automated:
1. As user `root` on the WalT server, run `walt-vpn-admin` and select the option for generating a setup script.
2. Transfer and run that setup script on the machine you want to configure as a VPN SSH entrypoint.

The generated script is small, you can obviously check it if you want. It just creates a user `walt-vpn` on the machine and populates its `$HOME/.ssh/authorized_keys` and `$HOME/.ssh/known_hosts` files appropriately.
It does not touch the global configuration of OpenSSH.


## Updating the VPN SSH entrypoint in WalT

To let WalT nodes use the newly installed VPN SSH entrypoint, use `walt-server-setup --edit-conf`. The third interactive screen is the one about VPN settings. When you update the VPN SSH entrypoint, an SSH connexion test will be automatically performed to verify your entry.

Once updated, the VPN nodes (Raspberry Pi 5 boards) will automatically reflash their EEPROM at next boot to take this change into account.
