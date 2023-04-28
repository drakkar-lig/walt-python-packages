
# Synchronizing a script based on expected logs

`walt log wait` allows to wait for a given log trace to be emitted. The command returns when it occurs.

Option `--issuers` allows to specify the set of devices monitored. If unspecified, the nodes you own (see [`walt help show node-ownership`](node-ownership.md)) will be selected.

The default behavior (`--mode ANY`) of this command is to wait until a logline emitted by **one** of the selected issuers matches the specified regular expression. In some cases, one may require a different behavior by using option `--mode ALL`. With this option, the command will wait until **all** selected issuers emit a given logline.

For example, let's consider an experiment run using scripts automatically started on node's bootup. These scripts send a logline `"DONE"` at the end of the experiment. In order to wait until all nodes are done with the experiment, the user can use:
```
$ walt node wait --mode ALL --nodes node1,node2,node3 DONE
```
This command will return when a logline including `"DONE"` has been received from all the specified experiment nodes.
