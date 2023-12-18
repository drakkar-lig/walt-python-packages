
# `walt-log-echo` logging tool

`walt-log-echo` is a logging tool provided on all nodes. It allows to emit loglines. For more info about WalT logging in general, see [`walt help show logging`](logging.md).

## Basic usage

You can run `walt-log-echo` like this:
```
[node]$ walt-log-echo <stream-name> <log-line>
```

This will emit a new `<log-line>` attached to logstream `<stream-name>`.
You can obviously call this in the experiment scripts you run on nodes.


## Advanced usage and performance tips

If you want to emit many log lines, you should consider using `walt-log-cat` instead. (see [`walt help show log-cat`](log-cat.md))

If you have means to record precise event timestamps (e.g. network timestamps), you can specify them by using option `--timestamp`:
```
[node]$ walt-log-echo --timestamp <ts> <stream-name> <log-line>
```
The `<ts>` value must be a UNIX timestamp, i.e. a floating point number of seconds since the 'EPOCH' (january 1, 1970). Without this option, the timestamp recorded will be the current time when `walt-log-echo` is run.


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

root@node1:~# walt-log-echo 'exp1' 'this is a logline of exp1'
root@node1:~#
```

And immediately the logline is catched on first terminal:
```
$ walt log show --realtime
17:35:53.147851 node1.exp1 -> this is a logline of exp1

```
