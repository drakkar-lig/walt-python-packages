
# How to install a switch on WalT platform network

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
* Network topology exploration

In order to enable those features, the switches you connect to `walt-net` must provide the following features:
* PoE (Power-Over-Ethernet) ports
* LLDP support (Link Layer Discovery Protocol)
* SNMP remote administration, with support for standard MIBs (POWER-OVER-ETHERNET.mib, IF.mib and LLDP.mib)


## Hardware recommendation

We recommend the switch netgear gs110tp. It is a cost-effective switch, with useful features in the context of
a WalT platform:
* 8 PoE ports
* LLDP support (Link Layer Discovery Protocol)
* remote administration using SNMP
* (and, if you ever need it in a particular setup, 802.1q support (VLANs))

This switch works well with its default settings.

Alternatively, WalT also works with switch TP-Link T1500G-10PS. You just have to configure it to request
its management IP through DHCP. Other default settings are OK.

Note: if you test another switch model, we would be happy to get the results of your test.


## Configuring the switch in WalT

By default, WalT may not detect that the equipment is a switch. Moreover, in some complex environments,
remote administration of a given switch by WalT may not be allowed. Thus, in order to let WalT use these
features, you must:

* Run `walt device show` and look for any new device that was detected by WALT server. The first field of the
  line will report the default name WALT gave to your switch. It should be `switch-<hhhhhh>` if WALT
  could detect it is a switch, or `unknown-<hhhhhh>` otherwise.
* Run `walt device rename "<type>-<hhhhhh>" "<your-switch-name>"` for convenience.
* If the device type is `unknown`, run `walt device config <your-switch-name> type=switch`.
* If your switch supports LLDP and/or PoE use `walt device config <your-switch-name> <settings>` to configure it. See next section.
* If LLDP is enabled, run `walt device rescan` and `walt device tree`. Your switch should appear in the topology tree.

Notes:
- LLDP only works between two devices (two switches, or a switch and a node) when both devices have LLDP enabled.
  On a node, this means the running walt image must embed a LLDP daemon.
- LLDP detection may need a few minutes.
- In any case, keep in mind that topology exploration and PoE reboots are optional features. It should not prevent
  you from working with nodes.


## Switch configuration settings

If you want to enable LLDP or PoE reboots, WalT server will have to communicate with the switch by using SNMP.
Thus you should specify SNMP configuration parameters `snmp.version` (with value `1` or `2`) and `snmp.community`.
Then, you can enable LLDP by specifying `lldp.explore=true`.
And finally you can enable node hard-reboots using PoE by specifying `poe.reboots=true`.
Note that you cannot enable `poe.reboots` without enabling `lldp.explore` (since WalT needs to know on which PoE
switch port a node is connected in order to hard-reboot it).

For instance, on the netgear gs110tp in its default configuration, one may run:
```
$ walt device config <switch-name> snmp.version=2 snmp.community='private' lldp.explore=true poe.reboots=true
```

For general information about this command, see [`walt help show device-config`](device-config.md).
