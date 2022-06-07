
# Connecting to a node's serial console

Sometimes, when working on the bootup procedure of a walt image, looking at the serial console
of a node may be useful.
Command `walt node console <node-name>` allows to provide such a console.

For now, this is only possible with virtual nodes: `walt node console` connects you to
the emulated serial console of the qemu process holding the virtual node.

The escape character used for key bindings is `<ctrl-a>`.
Use `<ctrl-a> d` to quit the console (disconnect).
Use `<ctrl-a> a` if you need to send `<ctrl-a>` to the node. (Note that `<ctrl-a> <ctrl-a>` works too.)
All other `<ctrl-a> <key>` combinations are ignored.

Important note: when entering the console, if the node has nothing to print the screen will remain empty.
If the node has finished booting, typing `<enter>` is usually enough to display the login prompt again.
Otherwise (e.g. the node hanged earlier because of a kernel panic), one can trigger the display of
bootup messages again by typing `walt node reboot <node-name>` in another terminal.

