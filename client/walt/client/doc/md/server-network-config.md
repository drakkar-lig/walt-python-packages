
# How to configure the network on a WalT server

## Overview

These instructions assume you are familiar with WALT network structure (see [`walt help show networking`](networking.md))
and with Debian operating systems.

In order to adapt to various network environments, the network configuration has to be edited.
Two files are concerned:
* `/etc/network/interfaces`, the classical network configuration file of Debian
* `/etc/walt/server.conf`, walt server configuration file

Content of file `/etc/walt/server.conf` should be JSON-compliant, except that we allow
single line comments (started by char `#`).

The following examples will clarify how these files should be configured.
It is advised to read these examples in the order they are presented below. At the end,
you should be able to combine them to match your own network setup.

## Scenario 1: very simple setup

In this scenario we have:
* Your usual LAN network (with DHCP service and internet connectivity) connected on eth0
* A dedicated WALT network (with dedicated network switches) connected on eth1

This can be configured as follows:
```
$ cat /etc/network/interfaces
auto eth0
iface eth0 inet dhcp

auto walt-net
iface walt-net inet manual
    up walt-net-config up
    down walt-net-config down

$
```

This means:
* we will let Debian manage our `eth0` interface the usual way
* we declare another interface called `walt-net`, and specify that this interface
  can be set `up` (resp. `down`) by running `walt-net-config up` (resp. `walt-net-config down`)

As you might guess, command `walt-net-config` will configure interface `walt-net` according
to the content of file `/etc/walt/server.conf`.

The content of this file could be:
```
$ cat /etc/walt/server.conf
{
    # network configuration
    # ---------------------
    "network": {
        # platform network
        "walt-net": {
            "raw-device": "eth1",
            "ip": "192.168.183.1/24"
        }
    }
}

$
```

This means that:
* our WALT network will be connected to physical interface `eth1`
* the WALT server will have its eth1 interface configured with IP address `192.168.183.1`
* the DHCP service of our WALT server will deliver IP addresses in the range `192.168.183.1/24`
  (to nodes and switches).

Notes:
* It is mandatory to declare `walt-net` in `/etc/walt/server.conf` as we did, because this
configuration file is read by other walt software services too, and they will need to find
the configuration of this network.
* The server address must be the first address of the range (setting `"ip": "192.168.183.2/24"`
for instance will cause problems).
* Since this plaform network is dedicated to WALT, the range of IP addresses you select is
not really important. Just set it large enough to support platform growth. Each device connected
to this network will get a permanent IP address lease, thus a "/24" network is perfectly fine
for a reduced setup (for instance a demo), not for a platform in a large building.


## Scenario 2: reusing a building network

In this scenario we have:
* A WalT server in the datacenter with 3 or more wired network interfaces
* The usual LAN network for servers (with DHCP service and internet connectivity) connected on eth0
* A dedicated WALT VLAN (configured in the building network equipments) connected on eth1
  (this is `walt-net`)
* The VLAN allowing remote management of building network equipments connected on eth2
  (this one should be called `walt-adm`)

Notes:
* This is a classical setup for a WALT platform with a large number of nodes. It is obviously
  interesting to reuse the existing wired network of the building, especially if network equipments
  provide optional WalT-related features (remote management through SNMP, LLDP neighbor discovery,
  and PoE). In this case, connecting a new walt node just requires to assign WALT VLAN to the target
  wall plug and connect the node to it.
* For more information about the remote switch administration features WALT can use,
  see [`walt help show networking`](networking.md).
* Of course, if you are not in charge of the building network, you will have to ask relevant people
  if they allow this configuration, and get relevant configuration parameters from them.

This scenario can be configured as follows:
```
$ cat /etc/network/interfaces
auto eth0
iface eth0 inet dhcp

auto walt-net
iface walt-net inet manual
    up walt-net-config up
    down walt-net-config down

auto walt-adm
iface walt-adm inet manual
    up walt-net-config up
    down walt-net-config down

$
$ cat /etc/walt/server.conf
{
    # network configuration
    # ---------------------
    "network": {
        # platform network
        "walt-net": {
            "raw-device": "eth1",
            "ip": "192.168.180.1/22"
        },
        # building network admin
        "walt-adm": {
            "raw-device": "eth2",
            "ip": "10.10.52.23/27"
        }
    }
}

$
```

Comparing to previous scenario, we just added the configuration for network `walt-adm`
(and selected a larger IP address range for `walt-net`). The IP address and range of network
`walt-adm` should be given by buiding network admins. This kind of administration LAN usually
uses a static IP configuration. If this is not the case, and DHCP is available instead, you
can also write `"ip": "dhcp"` in `walt-adm` section.


## Scenario 3: server with single wired LAN interface

Let's consider the case where the machine you want to setup as a WALT server has only one wired
interface (`eth0`).

### 3a: Using a wireless interface

If this machine has a wireless interface too (`wlan0`) you can obviously configure `walt-net` on `eth0`
and use `wlan0` for internet connectivity.
However, keep in mind that this internet connectivity will be used to upload or download walt images,
usually several hundreds of megabytes each. Thus, your wireless connection may not be the best option
for this kind of usage.
If you think it will be good enough, configuration setup should be pretty straightforward as long as you
have read scenario 1:

```
$ cat /etc/network/interfaces
auto wlan0
iface wlan0 inet dhcp
    wpa-ssid "<your-ssid>"
    wpa-psk  "<psk-key>"    # tip: $ wpa_passphrase <your-ssid> <your-password>

auto walt-net
iface walt-net inet manual
    up walt-net-config up
    down walt-net-config down

$
$ cat /etc/walt/server.conf
{
    # network configuration
    # ---------------------
    "network": {
        # platform network
        "walt-net": {
            "raw-device": "eth0",
            "ip": "192.168.183.1/24"
        }
    }
}

$
```

We just let Debian configure our `wlan0` interface, and let WalT manage `eth0` for its own usage.


### 3b: Using VLANs (IT expert)

For better performance, there is another alternative: use VLANs to manage both internet
connectivity and WALT platform LAN on the same physical interface.
An example of such a setup would be the following:

```
    ----------------------------------------
   | switch
    -----1---------2---------3---------4----
         |         |
         |         |              ---------
         |          -------------|WALT node|
         |                        ---------
        ----
    ---|eth0|-------------------------------
   |    ----                    WALT server
   |     |---------
   |     |         |
   |  -------   -------
   | |eth0.33| |eth0.34|
   |  -------   -------
   |     |         |
   |     |          ------ walt-out
   |      ---------------- walt-net

```

As usual the VLAN dedicated to WALT platform (with VLAN ID 33 in this example) is called `walt-net`.
Let us call `walt-out` the VLAN allowing internet connectivity (with VLAN ID 34 in this example).

This setup allows:
* The OS to get internet connectivity on virtual interface `eth0.34`
* WALT to communicate on its dedicated VLAN by using virtual interface `eth0.33`. For instance WALT will be able
  to reach the node connected on port 2 of the switch (if the switch is configured appropriately).

We describe below the appropriate configuration to set up those virtual interfaces, on WALT server side:

```
$ cat /etc/network/interfaces
auto walt-net
iface walt-net inet manual
    up walt-net-config up
    down walt-net-config down

auto walt-out
iface walt-out inet manual
    up walt-net-config up
    down walt-net-config down

$
$ cat /etc/walt/server.conf
{
    # network configuration
    # ---------------------
    "network": {
        # platform network
        "walt-net": {
            "raw-device": "eth0",
            "vlan": 33,
            "ip": "192.168.183.1/24"
        },
        # internet connectivity
        "walt-out": {
            "raw-device": "eth0",
            "vlan": 34,
            "ip": "dhcp"
        }
    }
}

$
```

In this configuration, we can notice usage of the `vlan` configuration entry. The rest of the configuration
should be obvious given previous scenarios.

Of course, this setup also requires appropriate VLAN configuration on the switch side, but this is outside the
scope of this documentation.

## Concluding remarks

You will probably have to adapt these scenarios to your own case, but this should be pretty obvious.
For instance, you may install WALT in a building with a server equipped with only 2 wired interfaces.
In this case you could connect `walt-net` and `walt-adm` on a single physical interface (using VLANs) and
`walt-out` on the other. This should be easily done by combining scenario 2 and 3b.

We currently do not support other OS network management systems (such as systemd-networkd).
However, our sole requirement is that interface `walt-net` (and `walt-adm` if relevant) has its
configuration described in file `/etc/walt/server.conf`.
There is no such requirement on other unrelated interfaces (such as the one providing internet
connectivity), and the admin may configure them with any system he likes.

