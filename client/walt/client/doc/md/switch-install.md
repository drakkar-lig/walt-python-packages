
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

Note: if you test another switch model, we would be happy to get the results of your test.


## Configuring the switch in WalT

The switch netgear gs110tp has all features described above enabled by default, so there is nothing to
configure on the switch itself.

However, by default, WalT may not detect that the equipment is a switch. Moreover, in some complex environments,
remote administration of a given switch by WalT may not be allowed. Thus, in order to let WalT use these
features, you must:

* Run `walt device show` and look for any new device that was detected by WALT server. The first field of the
  line will report the default name WALT gave to your switch. It should be `switch-<hhhhhh>` if WALT
  could detect it is a switch, or `unknown-<hhhhhh>` otherwise.
* Run `walt device rename "<type>-<hhhhhh>" "<your-switch-name>"` for convenience.
* Run `walt device admin <your-switch-name>` and answer questions. This will allow you to tell WALT whether it
  is allowed to request LLDP neighbor tables, and to alter status of PoE on its ports. You will also have to
  specify SNMP connection paramaters to this switch. On the netgear gs110tp for instance, in its default
  configuration, you should specify SNMP version "2" and community "private".
* Run `walt device rescan`.
* Run `walt device tree`. Your switch should appear in the topology tree.

In any case, keep in mind that topology exploration and PoE reboots are optional features. It should not prevent
you from working with nodes.

