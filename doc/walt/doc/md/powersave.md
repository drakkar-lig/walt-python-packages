
# Powersave feature: turning unused nodes off

When a PoE-powered WalT node has not been used for some time, WalT can automatically disable PoE (Power-over-Ethernet) on the corresponding switch port to save power.
For more info about PoE (Power-over-Ethernet) and the other optional features it allows, see [`walt help show optional-features`](optional-features.md).

When a user starts to interact with the node again (e.g, using `walt node shell` or `walt node wait`), WALT temporarily restores the PoE supply.

The concept of "unused node" is rather conservative:
* Only free nodes (cf. [`walt help show node-ownership`](node-ownership.md)) are considered.
* A free node is considered unused only after its `powersave.timeout` config value is reached.


# Requirements

The powersave feature requires that the switch supports PoE (obviously), SNMP (for remote requests) and LLDP (to know on which port the node is connected).
Then the `poe.reboots` config option of the switch must be explicitely enabled by using [``walt device config``](device-config.md).


## Configuring `powersave.timeout`

The `powersave.timeout` configuration option allows you to set the delay before an unused node is automatically powered off.
The value is expressed has a number of seconds. The default is 300, i.e. 5 minutes.

For example, the following will set the timeout of `rpi2-a` and `rpi2-b` to 3 minutes.
```
$ walt node config rpi2-a,rpi2-b powersave.timeout=180
```

You can also use choose to disable the automatic power off feature on a node or a set of nodes by using `powersave.timeout=none`.

For instance, the following will disable the automatic power off of all nodes on the platform:
```
$ walt node config all-nodes powersave.timeout=none
```

See [`walt help show device-config`](device-config.md) for more info about configuring WALT nodes and other devices.


## Important notes about the 'powersave' feature

Keep in mind that this 'powersave' feature only applies to free nodes.
WALT will never power off the nodes you own. So if you properly use commands `walt node acquire` and `walt node release`, you can certainly leave your nodes unattended during a long experiment: WALT will not power them off.

See [`walt help show node-ownership`](node-ownership.md) for more info.

If you want to host a discovery service on free nodes, using the `walt advanced set-free-nodes-image` command (cf. [`walt help show free-nodes`](free-nodes.md)), keep in mind that this service will not be available when nodes are switched off.

In this case you may want to disable the 'powersave' feature by setting `powersave.timeout=none` (see above).

Or if you still want the 'powersave' feature, then each time you wish to query the discovery service you must first force WALT to temporarily restore PoE.
If you are using the command line tool, you can use `walt node wait <node1>,<node2>,...` for this purpose. This command will automatically restore PoE and wait for the nodes to boot their OS image.
If you are using the python scripting features, then use the `<node>.wait()` or the `<set-of-nodes>.wait()` method.
