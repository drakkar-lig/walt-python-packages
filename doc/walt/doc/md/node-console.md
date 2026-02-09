
# Using and replaying the serial console of virtual nodes

Sometimes, when working on the bootup procedure of a walt image, looking at
the serial console of a node may be useful.
Command `walt node console <node-name>` allows to provide such a console.

For now, this is only possible with virtual nodes: `walt node console`
interacts with the emulated serial console of the `qemu` process emulating
the virtual node.

The escape character used for key bindings is `<ctrl-a>`.
* Use `<ctrl-a> d` to quit the console (disconnect).
* Use `<ctrl-a> a` if you need to send `<ctrl-a>` to the node, in
  realtime mode. (Note that `<ctrl-a> <ctrl-a>` works too.)
* All other `<ctrl-a> <key>` combinations are ignored.

Two modes are available, and combining them is also allowed.
The mode is selected by options `--realtime` and `--replay`.
* `walt node console <vnode>` (no options): realtime mode (default)
* `walt node console --realtime <vnode>`: realtime mode
* `walt node console --replay <replay-range> <vnode>`: replay mode
* `walt node console --replay <replay-range> --realtime <vnode>`: combined


## Realtime mode (default mode)

In this default mode, the console viewer interacts with the node in realtime.
The user input is transmitted to the node, and should be echo-ed on the
terminal.

Note that when entering the console, if the node has nothing to print,
the screen will remain empty.
If the node has finished booting, typing `<enter>` is usually enough to
display the login prompt again.
Otherwise (e.g. the node hanged earlier because of a kernel panic), one can
use the replay mode (see below) to diagnose the issue, or trigger the
display of bootup messages again by typing `walt node reboot <node-name>`
in another terminal.


## Replay mode

One can replay past console traffic by using a command such as:
`walt node console --replay -20m: myvnode`

This will replay what happened on the console of `myvnode` over the last
20 minutes and up to now.

The replay range, such as `-20m:` in this example, has the same format
as the history range of command `walt log show`. You can for instance
specify a log checkpoint as the start or end boundary.
See [`walt help show log-history`](log-history.md) for details.

Obviously, the replay mode does not allow actually interacting with the
node. In this case, any user input is discarded, except the `<ctrl-a> d`
combination allowing to exit the viewer.


## Combined mode

It is possible to combine the two modes, using a command such as:
`walt node console --replay -5m: --realtime myvnode`

This will replay what happened on the console of `myvnode` over the last
5 minutes and then switch to the realtime mode.
