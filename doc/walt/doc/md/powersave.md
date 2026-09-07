
# Powersave feature: turning unused nodes off

When a PoE-powered WalT node has not been used for 2 hours, WalT will automatically disable PoE (Power-over-Ethernet) on the corresponding switch port to save power.
For more info about PoE (Power-over-Ethernet) and the other optional features it allows, see [`walt help show optional-features`](optional-features.md).

When a user starts to interact with the node again (e.g, using `walt node shell` or `walt node wait`), WALT automatically restores the PoE supply.

The concept of "unused node" is rather conservative: only free nodes (cf. [`walt help show node-ownership`](node-ownership.md)) are considered unused after 2 hours.
Thus, thanks to commands `walt node acquire` and `walt node release`, experiments involving unattended nodes and lasting more than 2 hours cannot be interrupted by this power saving feature.

However, if you used the `walt advanced set-free-nodes-image` command to let free nodes host a discovery service (cf. [`walt help show free-nodes`](free-nodes.md)), keep in mind that this service will not be available when nodes are switched off. Whenever you wish to query this type of discovery service, you must let WALT restore PoE and wait for the node(s) to boot up.
If you are using the command line tool, you can use `walt node wait <node1>,<node2>,...` for this purpose.
If you are using the python scripting features, then use the `<node>.wait()` or the `<set-of-nodes>.wait()` method.

The powersave feature requires that the switch supports PoE (obviously), SNMP (for remote requests) and LLDP (to know on which port the node is connected).
Then it must be explicitely enabled by using [``walt device config``](device-config.md).
