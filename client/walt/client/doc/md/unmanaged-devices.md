
# Managing devices which do not implement WalT network booting

The WalT platform provides limited support for devices which do not implement a network bootloader
allowing WalT network booting.

In this case, the platform architecture can still be useful to provide automatic IP address
delivery, easy detection of new devices and simple device management.


## How to identify the new device in WALT

When WALT server detects a device for the first time, a log line is emitted.
Thus, you should be able to identify the new device by checking the logs as follows:

```
$ walt log show --platform --history -5m: "new"
10:31:37.603460 walt-server.platform.devices -> new device name=ecosignal-loragw-e7b3a7 type=unknown mac=58:bf:25:e7:b3:a7 ip=192.168.152.27
$
```

In this example we see that WALT registered this new device with name `ecosignal-loragw-e7b3a7`.
The hex chars are taken from the right side of the mac address.

You can give it a more convenient name, for instance:
```
$ walt device rename ecosignal-loragw-e7b3a7 loragw-17-room-426
```

## Providing internet connectivity to the device

One can allow this example device to access internet by running:
```
$ walt device config loragw-17-room-426 netsetup=NAT
```

After the device is rebooted, it will be able to access internet by using the WALT server as an IP gateway.


## Device management commands

Unmanaged devices do not boot a WalT image, thus the platform provides more limited support.
In particular, `walt node <command>` commands are not allowed in this case.
However, users can use the various `walt device <command>` commands to interact with the device,
such as `ping`, `shell`, and `expose` (cf. [`walt help show device-expose`](device-expose.md)).

