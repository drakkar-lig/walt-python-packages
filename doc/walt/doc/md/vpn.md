
# How to use WalT built-in VPN and distant nodes

## Introduction

**IMPORTANT NOTE:
This feature is experimental and currently being largely refactored (as of july 2024).
For now this documentation is kept as-is for historical purpose.**

WalT provides a built-in VPN subsystem allowing to deploy distant nodes. This feature is particularily useful
when experimenting with long-range protocols.

WalT VPN is based on **OpenSSH**, which should allow a very easy integration in your existing infrastructure.

Let's start with some important notes and vocabulary:
* WalT **vpn nodes** are Raspberry Pi 3 B+ boards with a custom OS flashed on their SD card.
* The VPN can (and should) be made accessible through a set of SSH proxies (usually one). This allows vpn nodes to
  access the WalT server without exposing the WalT server directly on internet.
* Such a SSH proxy is called a **VPN proxy** in this documentation.
* More specifically, the proxy that is exposed on internet (usually the only one) is also called **VPN entrypoint**.

Note: the WalT server can be used as a VPN entrypoint itself, but for security reason this is not recommended.

## About VPN nodes

Let us remind that regular WalT nodes boot their OS (i.e. WalT image) using a network bootloader.
Since network bootloaders are not able to handle a VPN, the bootup procedure of a VPN node is the following:

1. The *vpn node* (Raspberry Pi board) boots the OS that was flashed on its SD card.
2. The *vpn node* establishes a VPN based on a SSH tunnel to the VPN entrypoint.
3. The *vpn node* starts a kvm-based virtual machine connected to this VPN.
4. The new WalT node that appears in WalT is actually this kvm-based virtual machine.

Note: USB ports of the Raspberry Pi board are attached to the virtual machine.
Thus you can manipulate USB peripherals connected there as you would do with any regular WalT node.

## How to setup a VPN proxy (or entrypoint)

One can configure any UNIX-like machine as a VPN proxy (or entrypoint), as long as it provides:

* a running openssh service exposed on standard port 22 and allowing public key authentication
* basic UNIX commands used in the setup script (see below): `useradd` and `chown`

One can obtain a setup script just by typing the following command:
```
$ walt vpn setup-proxy
```

Then, one should transfer the script obtained and execute it on the machine which must be set up
as a WalT VPN proxy (or entrypoint).

The script will:

* create a user `walt-vpn` on the operating system
* setup file `/home/walt-vpn/.ssh/authorized_keys` appropriately.

## How to setup a VPN node

One may obtain a SD card image by typing:
```
$ walt vpn setup-node
```

The SD card image will be generated in current directory.
(One can re-use the SD card image for several vpn nodes, as long as the VPN entrypoint remains the same.)

Then, one can flash the image on a SD card by using command `dd` or similar, insert it on the Raspberry Pi board,
connect the board to a wired network and let it boot.

The bootup will follow the following steps:

1. get IP configuration from the wired network through DHCP.
2. if not done yet (first boot), try to get appropriate authentication keys from walt server (see below).
3. establish the VPN.
4. boot the kvm-based virtual machine that will act as a walt node.

On first boot, the vpn node is missing authentication keys. As a result, its ssh connection attempt is directed to
a specific authentication tool on the WalT server.

The WalT user who has installed the VPN node(s) should type the following command:
```
$ walt vpn monitor
```

When a node is attempting to get authentication material, this command displays a message asking to accept or
deny this new WalT vpn node.
It the user accepts it, the node will receive authentication keys and continue its bootup procedure.

Notes:

* If ever a node attempts to get authentication material and no such command was typed, the request is denied.
  In this case, the node waits a few seconds before issuing a new request.
* This authentication step runs only once when successful.
