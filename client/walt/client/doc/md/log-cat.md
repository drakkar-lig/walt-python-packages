
# `walt-log-cat` logging tool

`walt-log-cat` is a logging tool provided on all nodes. It allows to emit loglines. For more info about WalT logging in general, see [`walt help show logging`](logging.md).

## Basic usage

You can run `walt-log-cat` like this:
```
[node]$ <command...> | walt-log-cat <stream-name>
```

Output lines of `<command...>` will be transmitted up to WalT server and stored as log lines associated with the given log stream `<stream-name>`.
You can obviously use this in the experiment scripts you run on nodes.


## Advanced usage and performance tips

By default, or if option --ts-server is specified, timestamps will be taken upon reception on server side.

If you know the node is well synchronized (e.g., PTP is set up on this WALT image, or NTP and the node has booted several hours ago),
you may specify --ts-local instead:
```
[node]$ <command...> | walt-log-cat --ts-local <stream-name>
```
Timestamps will be taken locally on the node by using `date +%s.%N`.

If you can get even higher precision timestamps (e.g. network capture timestamps), you may use option --ts-provided instead:
```
[node]$ <command...> | walt-log-cat --ts-provided <stream-name>
```
In this case, output lines of `<command...>` must match the following form instead:
```
<float_timestamp> <log_line>
```
Values of `float_timestamp` must be unix timestamps (float number of seconds since 1970), as obtained with `date +%s.%N`.


## Simple example

I first run this in a first terminal:
```
$ walt log show --realtime

```

This will catch all loglines emitted from my nodes. (see [`walt help show log-realtime`](log-realtime.md) for more info)

Then, on a second terminal:
```
$ walt node shell node1
Caution: changes outside /persist will be lost on next node reboot.
Run 'walt help show shells' for more info.

root@node1:~# dmesg | walt-log-cat kernel-log
root@node1:~#
```

And immediately log lines are catched on first terminal:
```
$ walt log show --realtime
18:18:58.436790 node1.kernel-log -> [    0.000000] Booting Linux on physical CPU 0x0
18:18:58.469525 node1.kernel-log -> [    0.000000] Linux version 4.14.62+ [...]
[...]
```
