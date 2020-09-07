
# How to install and connect a new WalT node

## Introduction

The WALT server exposes the content of walt images to nodes using netboot-compatible protocols (TFTP and NFS).
Thus, WalT nodes can boot their OS over the network.
This means that the walt image is never transfered as a whole to the node: it remains on the server.

Given this fact, walt nodes just need a network bootloader configured appropriately.

WalT can handle various kinds of nodes, and users can even add support for a new kind of
node easily. Check-out [`walt help show new-node-support`](new-node-support.md) for more info.

Installation files can be found at https://github.com/drakkar-lig/walt-project/releases/latest.

The following sections will show how to set up a new node, depending on its model.
Then, last section will explain how walt users can start to use such a new node.


## PC nodes

Download image `pc-usb.dd.gz` at https://github.com/drakkar-lig/walt-project/releases/latest.
Flash it to a USB flash drive (a small one is enough, the image just needs a few tens of megabytes),
using unix tool `dd` or similar.

Then, any PC can be turned into a walt node:
* connect the PC to the WALT network
* boot on this USB flash drive (by setting BIOS/firmware options appropriately)

It should be compatible with most BIOS-based and UEFI-based machines, and old 32-bits PCs, provided
the network bootloader can handle the network card.


## Virtual nodes

WalT allows you to create virtual nodes. Virtual nodes are actually `kvm` virtual machines running
on the server. When you list nodes, virtual nodes will be displayed the same as PC nodes, because
their virtual hardware reflects the one of a standard PC.

In order to create a virtual node simply run:
```
$ walt node create <node-name>
```

And in order to remove it, run:
```
$ walt node remove <node-name>
```


## Raspberry Pi boards

### Hardware tips

WalT supports raspberry pi models B, B+, 2B, 3B, 3B+, and 4B.

We recommend raspberry pi model 3B+ or 4B, with the official PoE HAT addon board of the raspberry pi foundation.

You will also need at least one SD card for the first bootup (see below). You may use the same SD card to
perform this first bootup of each node.


### standard boot method: using a SD card

Download archive `rpi-sd-files.tar.gz` at https://github.com/drakkar-lig/walt-project/releases/latest.
Extract and copy files to a USB flash drive formatted the usual way (1 single partition, FAT32 fileystem).
A small one is enough, total size of files is just a few tens of megabytes.

Then:
* insert this SD card in its slot
* connect the board to the WALT network (and, if PoE is not provided, power it on)

The board will boot as a walt node.


### network boot method: no SD card

Raspberry Pi 3B+ and 4B boards have a more advanced firmware that may be used to boot over the network.
In this case, the SD card is no longer needed. However, due to incorrect firmware behavior (3B+ model),
and to the fact walt server has to detect the board model, you should boot the board at least once using
a SD card (see previous subsection).
Once done, you can remove the SD card, and next bootups should work without it.

Notes:
* The SD card is the most fragile part of a raspberry pi board, thus working without it prevents most
  common hardware problems. Note, however, that the smart bootup mechanism used in walt allows to keep
  the SD card readonly, which greatly improves its lifetime.
* This boot method is not as robust as the previous one: if, for any reason, communication with
  the server is temporarily broken, the board may fail to reboot and hang. (With the other boot method,
  the board would reboot as many times as required until the communication with the server is recovered.)
  If PoE is used to power the board, and PoE reboots are allowed on the switch, then walt will allow you
  to "hard-reboot" (i.e. power-cycle) the board remotely. Otherwise, one would have to manually disconnect
  and reconnect the power source of the board to unblock it.
* On the Raspberry Pi 4B board, the network boot method of the firmware must be activated first. This is
  done automatically by script `/bin/on-bootup` of default image. As a result, when you will boot the
  board for the first time, with a SD card, the firmware update will be applied and the board will
  automatically reboot. Once this second boot is done, the board can work without the SD card.


## How to identify and use the new node

When WALT server detects a node for the first time, it names it 'node-<6-hex-chars>' (for instance node-8a7b6c).
The hex chars are taken from the right side of the node's mac address.

If LLDP (link layer discovery protocol) is available, just wait a little (10 minutes) after you have booted
the new node, for the LLDP table to be updated on the switch.

Then run:
```
$ walt device rescan
$ walt device tree
```

The tree view should display your new node connected on the appropriate switch and port number.

If LLDP is not available, use `walt node show --all` and look for those named 'node-<6-hex-chars>'.
The node model (e.g. `rpi-b-plus`, `rpi-2-b`, etc.) is diplayed too.
If unsure which node is which, you can use `walt node blink <node>`. Currently, on raspberry pi boards,
this will make a tiny led blink in heartbeat mode. Or use `walt node reboot <node>` and check which
board is temporarily powered off.

In any case, as soon as the node is identified, it is strongly advised to rename it. A naming scheme
such as `<type>-<location>-<id>` is handy. For instance, considering the node is in room 412:
```
$ walt device rename node-8a7b6c rpi3b-412-A
```

Troubleshooting notes:
* If ever the node failed to boot over the network (this probably means the network is misconfigured),
  the server might still detect it but it may not know that this device is a node. Thus, the server
  will name it 'unknown-<6-hex-chars>' instead of 'node-<6-hex-chars>'. And the node will not appear
  when typing `walt node show --all`. You can use `walt device show` instead.
  The first time the node boots correctly, it will be automatically renamed to 'node-<6-hex-chars>',
  and appear in the output of `walt node show --all`.
* In case of trouble, you can monitor walt service logs on the server, while connecting the new node,
  by typing `journalctl -f -u walt-server`. Or use a network sniffer (such as wireshark).

