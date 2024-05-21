
# WalT node installation

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

Any PC can be turned into a walt node.

If the PC supports PXE booting, the procedure is obvious:
1. Connect the PC to the WALT network.
2. Select "PXE booting" as the first boot option (by using the BIOS/firmware screen).

If not, download image `pc-usb.dd.gz` at https://github.com/drakkar-lig/walt-project/releases/latest.
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

### Hardware tips

WalT supports raspberry pi models B, B+, 2B, 3B, 3B+, 4B, and Pi-400.

We recommend raspberry pi model 3B+ or 4B.

PoE support can be provided by the official PoE HAT addon board of the raspberry pi foundation,
but it is a little noisy.

As an alternative, we have also tested compact external PoE splitters (YuanLey brand) which are cheaper,
more silent (no fan), and work fine.
Take care on puchasing the right model for powering your board:
- rpi 4B boards need a splitter model with a USB-C connector,
- rpi 3B+ boards need a splitter model with a USB micro-B connector.

Raspberry Pi models earlier than 3B+ require a SD card for bootup.
Newer models can run with or without a SD card (see below).


### Standard boot method: using a SD card

Download archive `rpi-sd-files.tar.gz` at https://github.com/drakkar-lig/walt-project/releases/latest.
Extract and copy files to a USB flash drive formatted the usual way (1 single partition, FAT32 fileystem).

Then:
* insert this SD card in its slot
* connect the board to the WALT network (and, if PoE is not provided, power it on)

The board will boot as a walt node.


### Network boot method: no SD card

Raspberry Pi 3B+ and 4B boards have a more advanced firmware that may be used to boot over the network.
In this case, the SD card is no longer needed.
But in any case, you can still use a SD card if you wish, see below for advice.

Raspberry Pi 3B+ boards without a SD card should directly boot as a walt node, no specific setup steps
are needed.

Considering 4B boards, depending on the board release, the default boot order may or may not include
a network boot attempt. When connected to a display at bootup, the boot order is displayed on the
diagnosis screen. If it prints "0xf41", then network boot is missing (network boot is digit "2").
In this case, you will need to flash the eeprom to activate the network boot, by booting at least once
with a SD card, as described below.


### 4B boards: flash the EEPROM to enable network booting (optional)

If using a 4B board, the eeprom can be flashed to enable network booting. Thanks to appropriate
boot files in `rpi-sd-files.tar.gz` this is done automatically when the board is first booted with
a SD card prepared for walt (see standard boot method above). The boot order we select is
"try network boot, if it fails, try SD card boot, and if it fails too, restart".

Important note: in order to prevent this eeprom flashing operation to repeat each time the board is
rebooted with the SD card, the firmware renames `recovery.bin` to `RECOVERY.000`. Thus, if you want to
use the same SD card to update the boot order of several 4B boards, after each boot rename `RECOVERY.000`
back to `recovery.bin` on the SD card before inserting it in another board.


### Advices for selecting a boot method

On the hardware side, the SD card is the most fragile part of a raspberry pi board, thus working without
it prevents most common hardware problems. Note, however, that the smart bootup mechanism used in walt
allows to keep the SD card readonly, which greatly improves its lifetime.

On the software side, the boot procedure based on the SD card is slightly more robust: if, for any
reason, network communication with the server is temporarily broken, the SD card boot procedure will
take care of rebooting as many times as required until the communication with the server is recovered.
The board firmware is not as smart and may hang forever in this case. If PoE is used to power the board,
and PoE reboots are allowed on the switch, then walt will allow you to "hard-reboot" (i.e. power-cycle)
the board remotely. Otherwise, one would have to manually disconnect and reconnect the power source of
the board to unblock it.

So our advices would be:
1. If your 3B+ / 4B boards are powered by PoE switches walt can control, remove SD cards
2. If not, use SD cards.


## Google Coral Dev Boards

First, follow the standard startup procedure at https://coral.ai/docs/dev-board/get-started.
Then run the following on the board (with a proper internet access):
```
$ cd /tmp
$ wget https://github.com/drakkar-lig/walt-project/releases/latest/download/coral-devb-boot.tar.gz
$ cd /boot
$ mv boot.scr boot.scr.orig
$ tar xfz /tmp/coral-devb-boot.tar.gz
```

You can now connect the board to a WALT network and it will boot as a WALT node.
For PoE, we recommend the compact PoE splitter with a USB-C connector (cf. hardware tips about raspberry pi boards above).


## How to identify and use the new node

When WALT server detects a node for the first time, a log line is emitted.

Thus, you should be able to identify the new node by checking the logs as follows:
```
$ walt log show --platform --history -5m:
10:45:49.188989 walt-server.platform.devices -> new node name=node-f26782 model=rpi-3-b-plus mac=b8:27:eb:f2:67:82 ip=192.168.152.14
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
