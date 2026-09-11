
# Powersave feature: turning unused nodes off

When a PoE-powered WalT node has not been used for 2 hours, WalT will automatically disable PoE (Power-over-Ethernet) on the corresponding switch port to save power.
For more info about PoE (Power-over-Ethernet) and the other optional features it allows, see [`walt help show optional-features`](optional-features.md).

When a user starts to interact with the node again (e.g, using `walt node shell` or `walt node wait`), WALT automatically restores the PoE supply.

The concept of "unused node" is rather conservative:
* Only free nodes (cf. [`walt help show node-ownership`](node-ownership.md)) are considered.
* A free node is considered unused only after the `powersave.timeout` config value is reached.


## Configuring `powersave.timeout`

The delay after which a free node will be considered unused can be configured in three ways:
* Value 60 or more: when a node is released, wait for this amount of seconds before powering the node off. After the node is powered off, if someone runs a command such as `walt node shell`, the node will temporarily be powered back for the time of the command, and powered off again after the configured delay.
* Value 0: as soon as the node is released (i.e., someone released it) it is powered off. After that, attempts to run commands such as `walt node shell` will return an error indicating the node is in a "permanent powersave mode" and therefore unusable.
* Value 'none': in this case, the node will never be powered off.

Keep in mind that this setting only impacts free nodes.
WALT will never power off the nodes you own. So if you properly use commands `walt node acquire` and `walt node release`
ICI





See [`walt help show node-ownership`](node-ownership.md) for more info.

Thus, thanks to commands `walt node acquire` and `walt node release`, experiments involving unattended nodes and lasting more than 2 hours cannot be interrupted by this power saving feature.

However, if you used the `walt advanced set-free-nodes-image` command to let free nodes host a discovery service (cf. [`walt help show free-nodes`](free-nodes.md)), keep in mind that this service will not be available when nodes are switched off. Whenever you wish to query this type of discovery service, you must let WALT restore PoE and wait for the node(s) to boot up.
If you are using the command line tool, you can use `walt node wait <node1>,<node2>,...` for this purpose.
If you are using the python scripting features, then use the `<node>.wait()` or the `<set-of-nodes>.wait()` method.

The powersave feature requires that the switch supports PoE (obviously), SNMP (for remote requests) and LLDP (to know on which port the node is connected).
Then it must be explicitely enabled by using [``walt device config``](device-config.md).
