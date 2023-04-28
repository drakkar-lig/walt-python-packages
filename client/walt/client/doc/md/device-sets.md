
# Device and node sets: use several devices at once

Many walt commands allow you to target several devices (e.g. nodes, switches) at once.

For instance:
```
$ walt node run my-nodes hostname
```

If one types `walt node run --help`, one can see that the first parameter is a `node_set`, thus allowing
to specify several nodes.
If one types `walt device rescan --help`, one can see that the first parameter is a `device_set`, thus allowing
to specify several devices, and the default value of this optional parameter is `server,explorable-switches`.

To specify this kind of command parameter, the following options are allowed:
* specify a single device (e.g. `node1`)
* specify a coma-separated list of devices (e.g. `node1,node2,node3`) with no space
* use one of the predefined sets (see below)
* combine previous options (e.g. `server,explorable-switches`)

Here is the list of predefined sets:
* `my-nodes`: nodes the user currently owns (see [`walt help show node-ownership`](node-ownership.md))
* `free-nodes`: nodes that no one currently owns
* `all-nodes`: all nodes of the platform
* `all-switches`: all switches of the platform
* `all-devices`: all devices (nodes, switches, unknown devices, and the server)
* `explorable-switches`: all switches with `lldp.explore` set to `true`

