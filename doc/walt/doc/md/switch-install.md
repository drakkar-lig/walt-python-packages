
# Switch installation in WalT network

## Scope

For a general view of networking topic, see [`walt help show networking`](networking.md) first.

This documentation page explains how to plug and configure a switch connected to the dedicated WalT platform
network (sometimes called `walt-net`).

In complex scenarios (see [`walt help show server-network-config`](server-network-config.md)), the first switch connected to WALT server
may have to be configured for using VLANs. This is outside the scope of this configuration, because it highly
depends on the switch model you use and the overall network environment where the platform is deployed. In
this case you should contact your network admins.


## Recommended switch features

The following WalT features are optional:
* Node "hard-reboots" (being able to remotely stop powering a given node to force a reboot in case of problem)
* Automatic power savings (by powering off unused nodes)
* Network topology exploration

In order to enable those features, the switches you connect to `walt-net` must provide the following features:
* PoE (Power-Over-Ethernet) ports
* LLDP support (Link Layer Discovery Protocol)
* SNMP remote administration, with support for standard MIBs (POWER-OVER-ETHERNET.mib, IF.mib and LLDP.mib)

If LLDP.mib is missing, WALT will try to analyse the forwarding tables instead (BRIDGE.mib or Q-BRIDGE.mib);
These alternate MIBs should suffice as long as you connect and configure these switches on WALT one at a time.

See [`walt help show optional-features`](optional-features.md) for more info.


## Hardware recommendation

We recommend the switch Netgear GS110TP. It is a cost-effective switch, with useful features in the context of
a WalT platform:
* 8 PoE ports
* LLDP support (Link Layer Discovery Protocol)
* remote administration using SNMP
* (and, if you ever need it in a particular setup, 802.1q support (VLANs))

This switch works well with its default settings; it comes with a default SNMPv2 community named 'private'
with read-write rights.

The switch Netgear GS324TP works equally well with WALT; It provides 24 PoE+ ports and has very similar
network management features. However, it has no default SNMPv2 community configured, so you will have
to connect to its web interface (`http://<switch-ip>`) to define an SNMPv2 community with read-write rights
to be used by WALT.

Alternatively, WalT was also tested with the switch TP-Link T1500G-10PS. You just have to configure it to
request its management IP through DHCP. Other default settings are OK.

At LIG, WalT also communicates with switches of the building network, which are Avaya 4850GTS-PWR+
switches (48 PoE ports).
These switches provide all optional remote management features useful for WALT too.

Note: if you test another switch model, we would be happy to get the results of your test.


## How to identify the new switch in WALT

When WALT server detects a switch for the first time, a log line is emitted.
Thus, you should be able to identify the new switch by checking the logs as follows:

```
$ walt log show --platform --history -5m: "new"
10:50:15.498660 walt-server.platform.devices -> new switch name=switch-18d55d mac=6c:b0:ce:18:d5:5d ip=192.168.152.11
$
```

If WALT is unable to detect this device is a switch, the log line will look like this instead:
```
10:50:15.498660 walt-server.platform.devices -> new device name=unknown-18d55d type=unknown mac=6c:b0:ce:18:d5:5d ip=192.168.152.11
```
In this example we see that WALT registered this unknown device with name `unknown-18d55d`.
The hex chars are taken from the right side of the switch mac address.

In such a case, run the following to let WALT know this new device is actually a switch:
```
$ walt device config unknown-18d55d type=switch
Renaming unknown-18d55d to switch-18d55d for clarity.
Done.
$
```

In any case, when your switch is identified you can give it a more convenient name, for instance:
```
$ walt device rename switch-18d55d switch-netgear-426
```


## Enabling LLDP and/or PoE

In some complex environments, remote administration of a given switch by WalT may not be allowed;
or LLDP/PoE may not be available. Thus, these features are disabled by default. As a result, WALT
must be explicitely allowed to use these features on a given switch, by using `walt device config`
(see next section).

When LLDP is enabled, after a little time (e.g. 10 minutes) you can run `walt device rescan` and
`walt device tree`; your switch should appear in the network topology tree.

Notes:
- LLDP only works between two devices (two switches, or a switch and a node) when both devices have LLDP enabled.
  On a node, this means the running walt image must embed a LLDP daemon.
- In any case, keep in mind that topology exploration and PoE reboots are optional features. It should not prevent
  you from working with nodes.


## Switch configuration settings

If you want to enable LLDP or PoE reboots and power savings, WalT server will have to communicate with the switch by using SNMP.
Thus you should specify SNMP configuration parameters `snmp.version` (with value `1` or `2`) and `snmp.community`.
Then, you can enable LLDP by specifying `lldp.explore=true`.
And finally you can enable node hard-reboots using PoE by specifying `poe.reboots=true`.
This setting also activates automatic power savings.
Note that you cannot enable `poe.reboots` without enabling `lldp.explore` (since WalT needs to know on which PoE
switch port a node is connected in order to hard-reboot it or power it off).

For instance, on the Netgear GS110TP in its default configuration, one may run:
```
$ walt device config <switch-name> snmp.version=2 snmp.community='private' lldp.explore=true poe.reboots=true
```

For general information about this command, see [`walt help show device-config`](device-config.md).

Last note: to make the network view (output by `walt device tree`) of a large building more readable, its is possible to rename the switch ports.
See [`walt help show device-port-config`](device-port-config.md).
