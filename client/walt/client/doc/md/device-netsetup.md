
# Changing network mode of a WalT node or device

## Introduction

**In the default network mode, the wired platform network is isolated from internet.** This is the
preferred mode because it ensures higher experiment reproducibility.

An example about the impact on reproducibility is the following: most operating systems, in their
default configuration, will try to download and install security updates on bootup. Obviously, if
this is not disabled on the walt image, and the walt node can access internet, it may cause
reproducibility problems on some experiments.

However, some experiments may actually require internet access on a specific node (e.g. for access
to a web service). Moreover, it is sometimes handy to let a node access internet during the
debugging phase, and then disable it.

Network modes can also be configured on other devices of network `walt-net`, such as unmanaged devices
(cf. [`walt help show unmanaged-devices`](unmanaged-devices.md)), not only on nodes.

## Network modes: LAN and NAT

Two network modes can be set up on a node (or device):
* **LAN**. This is the default mode. Nodes (and devices) can communicate with each other and with the
  server over the wired network. But they cannot reach internet.
* **NAT**. Activating this mode on a specific node or device allows it to reach internet. (Of course,
  it can still reach other nodes and server with this mode.) On bootup, the selected node or device
  will get an appropriate DHCP response and will set its default gateway to the IP of walt server. On
  the server side, firewall configuration will be updated appropiately to allow network address
  translation to and from this device.


## Updating network mode of a walt node or device

Use the following command:
```
$ walt node config <node-name> netsetup=[NAT|LAN]
```

or
```
$ walt device config <device-name> netsetup=[NAT|LAN]
```

Then reboot the node or device.
