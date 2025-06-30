
# WalT node installation

## Introduction

The WALT server exposes the content of walt images to nodes using netboot-compatible protocols (TFTP and NFS).
Thus, WalT nodes can boot their OS over the network.
This means that the walt image is never transfered as a whole to the node: it remains on the server.

Given this fact, walt nodes just need a network bootloader configured appropriately.

WalT can handle various kinds of nodes, and users can even add support for a new kind of
node easily. Check-out [`walt help show new-node-support`](new-node-support.md) for more info.

Installation files can be found at https://walt-project.liglab.fr/downloads.

The following sections will show how to set up a new node, depending on its model.
Then, last section will explain how walt users can start to use such a new node.


## PC nodes

Any PC can be turned into a walt node.

If the PC supports PXE booting, the procedure is obvious:
1. Connect the PC to the WALT network.
2. Select "PXE booting" as the first boot option (by using the BIOS/firmware screen).

If not, download image `pc-usb.dd.gz` at https://walt-project.liglab.fr/downloads.
Flash it to a USB flash drive (a small one is enough, the image just needs a few tens of megabytes),
using unix tool `dd` or similar. Then:
1. Plug the USB flash drive to the PC.
2. Connect the PC to the WALT network.
3. Boot on the USB flash drive (by using the BIOS/firmware screen).

The USB image should be compatible with most BIOS-based and UEFI-based machines, and old 32-bits PCs,
provided the network bootloader can handle the network card.


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

WalT supports the following Raspberry Pi models:

|     | Recommended PoE splitter    | SD-card | VPN node | Setup task        |
|-----|-----------------------------|---------|----------|-------------------|
| B   | external(1)                 | Yes     | No       | SD-card(2)        |
| B+  | external(1)                 | Yes     | No       | SD-card(2)        |
| 2B  | external(1)                 | Yes     | No       | SD-card(2)        |
| 3B  | external(1)                 | Yes     | No       | SD-card(2)        |
| 3B+ | external(1) or official(3)  | No      | No       | None!(4)          |
| 4B  | external(5) or official(3)  | No      | No       | Set boot-order(4) |
| 5B  | external(5) or waveshare(6) | No      | Yes(7)   | Set boot-order(4) |

Notes:
1. Use a PoE splitter providing micro-USB type B connectivity.
2. See "Booting older models with a SD card" below.
3. You can purchase the official "Raspberry Pi PoE+ HAT". It can fit in the official Rpi 3B+ or 4B cases. However, the integrated fan is a little noisy (coil whine). We have been aware of defective boards where this coil whine sound was quite loud. If you receive such a defective board, you can probably get a warranty replacement.
4. See "Booting recent models" below.
5. Use a PoE splitter providing USB-C connectivity. Model 5B needs more power (PoE+ is required for a reliable behavior), especially if you connect USB peripherals; look for PoE+ compatibility and output power 4A.
6. At the time of this writing there is no official PoE HAT for model 5B, but we tested the Waveshare PoE HAT model F successfully. Note that it is not compatible with the official case.
7. See [`walt help show vpn`](vpn.md).

We highly recommend powering Raspberry Pi nodes with PoE.
In this case, and if PoE reboots are allowed on the switch, then walt can
automatically "hard-reboot" (i.e. power-cycle) a board remotely if ever it
stops responding.

The following story highlights the importance of PoE.
In an industrial context, we experienced stability issues with a testbed of
100 Raspberry Pi boards. Approximately once every 2000 reboots, a board could
fail to boot and stopped at the "rainbow" screen.
But this testbed was later replaced with another one, PoE-powered, so the
automatic "hard-reboot" feature allowed to reach complete reliability.


### Booting recent models

Raspberry Pi 3B+ and newer boards have an advanced firmware that allows us to
bootstrap the network boot procedure directly.
So these boards should be installed without a SD card.

The 3B+ model is the easiest: just remove any SD card, connect the board
to the walt network, power on the board (preferably with PoE), and it should boot
directly as a walt node.

Considering Raspberry Pi 4B and 5B boards, depending on the board release, the
default boot order may or may not include a network boot attempt.
(If it does, then the setup is as easy as the one of the 3B+.)
When connected to a display at bootup, the boot order is displayed on the
diagnosis screen. If it prints "0xf41", then network boot is missing (network boot
is digit "2"). In this case, you need to boot the board just once with a SD card
containing recovery files for updating the boot order:
1. Checkout https://walt-project.liglab.fr/downloads and download archive `rpi-4-sd-recovery.tar.gz` or `rpi-5-sd-recovery.tar.gz`
2. Extract and copy files to a SD card formatted the usual way (1 single partition, FAT32 fileystem)
3. Insert this SD card in its slot
4. Power on the board and wait until the green LED starts blinking repeatedly (and if a HDMI display is connected, a plain green screen is displayed)
5. Power off the board and remove the SD card (you can obviously reuse it for updating the boot order of other boards)
6. Connect the board (without the SD card) to the WALT network and power it on (preferably with PoE); the board will boot as a walt node.


### Booting older models with a SD card

Older models cannot boot from the network directly, so they need a SD card containing
network bootloader files:
1. Download archive `rpi-sd-files.tar.gz` at https://walt-project.liglab.fr/downloads.
2. Extract and copy files to a SD card formatted the usual way (1 single partition, FAT32 fileystem).
3. Insert this SD card in its slot
4. Connect the board to the WALT network and power it on (preferably with PoE); the board will boot as a walt node.

The SD card is a fragile part. However, the network booting mechanism used in walt
allows to keep the SD card readonly, which greatly improves its lifetime.


## Google Coral Dev Boards

First, follow the standard startup procedure at https://coral.ai/docs/dev-board/get-started.
Then run the following on the board (with a proper internet access):
```
$ cd /tmp
$ wget https://walt-project.liglab.fr/files/coral-devb-boot.tar.gz
$ cd /boot
$ mv boot.scr boot.scr.orig
$ tar xfz /tmp/coral-devb-boot.tar.gz
```

You can now connect the board to a WALT network and it will boot as a WALT node.
For PoE, use a PoE splitter providing USB-C connectivity.


## How to identify and use the new node

When WALT server detects a node for the first time, a log line is emitted.

Thus, you should be able to identify the new node by checking the logs as follows:
```
$ walt log show --platform --history -5m:
10:45:49.188 walt-server.platform.devices -> new node name=node-f26782 model=rpi-b [...]
$
```

Important notes:
* The first time a given model of walt node is connected, the server has to download a default walt image to handle it, which takes time.
* In this more complex case, the logs will first indicate the new node is a device of 'unknown' type, and once the image is downloaded, it will be turned into a real walt node.
* `--platform` allows to select platform internal logs (as opposed to experiment logs generated by walt nodes).
* `--history -5m:` allows to select logs issued up to 5 minutes ago and up to now (you may increase this number
  if the node was connected longer ago).

In this example the log line indicates that the new node has been named `node-f26782`.
The hex chars are taken from the right side of the node's mac address.
As soon as the node is identified, it is strongly advised to rename it. A naming scheme
such as `<type>-<location>-<id>` is handy. For instance, considering the node is in room 412:
```
$ walt device rename node-f26782 rpi3bp-412-A
```

The new node first boots a default image, thus it belongs to nobody.
It will be listed as a "free" node when you use `walt node show --all`.
To make this node yours, run `walt node acquire <node>` or let it boot one of your images by using `walt node boot <node> <image>`
(see [`walt help show node-ownership`](node-ownership.md)).

Troubleshooting notes:
* If ever the node failed to boot over the network (this probably means the network or the node
  bootloader is misconfigured), the server might still detect it but it may not know that this device
  is a node. In this case `walt log show` will still print a line but mention a `"new device"`
  instead of a `"new node"`. This node will obviously not appear when typing `walt node show --all`, but
  it will be listed when you use `walt device show`.
  The first time the node boots correctly, its type will be automatically updated and it will appear
  in the output of `walt node show --all`.
* In case of trouble, you can monitor walt service logs on the server, while connecting the new node,
  by typing `journalctl -b -afu walt-server`. Or use a network sniffer (such as wireshark).
