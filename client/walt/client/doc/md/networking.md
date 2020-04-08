
# WalT network structure

## Overview

The following figure describes the network architecture of a WALT platform in its simplest form.

```
          --------    --------
         |switch  |  |switch  |
          --------    --------
            | | |      | |  |
            | |  ------  |   -------
            | |          |          |
            | |   -----  |   -----  |   -----
            |  --|node1|  --|node2|  --|node3|
            |     -----      -----      -----
 '          |
 |walt-out  |walt-net
 ---------------------------
|WALT server                |
 ---------------------------
```

The WALT server is the brain of the platform. It stores the WALT images and exposes them
to nodes over the network.

Nodes use a network booting procedure (TFTP + NFS) to boot the operating system contained
in a selected WALT image.


## walt-net and walt-out networks

As shown in the figure, there are two main requirements regarding network setup:
* The server should have internet connectivity, in order to be able to communicate with the docker hub.
  In these documentation pages, this is sometimes refered as `walt-out`.
* The platform LAN (or VLAN) MUST be fully dedicated to WALT. The WALT server will fully manage this
  platform network, by providing various network services, such as DHCP, NFS, TFTP, PTP, etc. We call
  this platform network `walt-net` in these documentation pages and in configuration files.

Of course we can cascade several switches to extend `walt-net`, as shown on the figure.
Caution: connecting a walt node directly to the server (with no intermediate switch) will not work!

Isolating networks `walt-net` and `walt-out` allows better experiment reproducibility. Thus, in the
default configuration, they are isolated one from each other. However, one can alter this configuration
and allow a specific set of nodes to access internet. Check-out [`walt help show node-netsetup`](node-netsetup.md)
for more info.


## Network switch remote administration features

The WALT server, if allowed, may send SNMP queries to a given switch, for one of these two purposes:
* retrieve LLDP data (Link Layer Discovery Protocol), for network discovery
* activate / deactivate PoE on one of the ports (for remotely hard-rebooting a walt node)

These two requests are disabled by default. You can activate and configure them for a given switch
using `walt device config <switch> <parameter>...` (see [`walt help show device-config`](device-config.md)).

Of course this is only possible if the switch provides related features.
Check-out [`walt help show switch-install`](switch-install.md) for more info.


## walt-adm: optional network admin network

If WALT is installed in a building and reuses an existing network infrastructure, there is usually
a dedicated VLAN already in place for remote administration of switches.

Instead of allowing remote administration (i.e. SNMP requests) from network `walt-net`, admins usually
prefer to give the WALT server access to this dedicated admin network.

We call this optional network `walt-adm` in these documentation pages and in configuration files.

Note that if `walt-adm` is configured, WALT may send SNMP requests on both `walt-net` and `walt-adm`
networks. To clarify, let's consider WALT has been installed in a large building, and some wall plugs
have been dedicated to the experimentation network (thus there are associated to `walt-net`).
In order to perform an small experiment with a few nodes on your desk, you could connect a small
switch to one of these wall plugs, and connect your nodes on it. In this case, WALT will have to use
`walt-net` to reach this small switch, and `walt-adm` to reach the switch managing the wall plug.

