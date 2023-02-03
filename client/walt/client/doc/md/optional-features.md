
# Optional features of a WalT platform

Depending on the network switches and their configuration, WalT may provide the following valuable features.


## Preliminary note about SNMP

SNMP is the Simple Network Management Protocol. It allows to automate remote administration tasks on a network equipment.
Most professional grade switches handle this protocol.
The following optional features of WalT are not available otherwise.


## Automated discovery of the network topology

LLDP is the Link Layer Discovery Protocol. It allows a network equipment to know the list of its immediate (i.e., at mac layer) neighbors.
If a network switch of the WalT network has this feature and accepts remote SNMP queries from the WalT server, then the WalT server
can get the list of devices connected on it.
When configured to do so (see below), the WalT server can query all switches (command `walt device rescan`) and then display a whole tree of the WalT network (command `walt device tree`).


## PoE for simplified deployment and hard-reboot feature

PoE means Power over Ethernet. It consists of using the same ethernet cable for bringing both power and data to a device.
Having one cable per node instead of two obviously simplifies platform deployment.

PoE corresponds to a standard protocol, named 802.3af (or 802.3at for PoE+) which the devices at both ends must comply with.
Thus, in the case of WalT, we recommend to buy PoE compliant switches, and to power the nodes with PoE when possible.
For instance, raspberry pi boards 3B+ and 4B can be powered by a "PoE HAT" designed by the raspberry pi foundation.
Older models can rely on an external PoE splitter such as the Tp-Link TL-POE10R.

If a switch provides SNMP, LLDP and PoE features, WalT also implements one more interesting feature: PoE hard-reboots.
If a PoE-powered node is stuck for some reason (the experiment code introduced a bug in the Linux kernel, a temporary firmware or network issue occured, etc.),
the WalT server may be able to power-cycle it remotely, to force a reboot.
The command `walt node reboot <node>` actually tries a standard reboot request first, and if the node does not reply, it will automatically run this hard-reboot operation if available.
The power-cycle operation is implemented by sending a request to the switch to stop powering the port where the node is connected. After one second, another request is sent
to recover the powering.

Note: the switch must support PoE (obviously), SNMP (for remote requests) and LLDP (to know on which port the node is connected).


## Activating these optional features in WalT

In some complex environments, remote administration of a given switch by WalT may not be allowed; or LLDP/PoE may not be available.
Thus, these features are disabled by default. As a result, WALT must be explicitely allowed to use these features on a given switch,
by using [``walt device config``](device-config.md).

