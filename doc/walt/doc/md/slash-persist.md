
# The directory /persist on nodes

The directory `/persist` is where users should store experiment result
files. It is actually a read-write network file system share, so files
written there are actually stored on the WalT server.

When using the default boot mode, `network-volatile`, or the
`hybrid-volatile` mode, file changes made on the node are discarded each
time the node reboots. See [`walt help show boot-modes`](boot-modes.md).
In these cases, this directory `/persist` is the only one preserved
accross reboots.

Note that on server side, a separate storage is used for each pair of
user and node. So if you reuse a node which was previously used by
someone else, you won't see the files this person stored there. Instead,
`/persist` will appear empty or with the files you stored last time
you used this node.
