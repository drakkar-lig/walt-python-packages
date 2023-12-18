
# `walt-log-monitor` logging tool

`walt-log-monitor` is an advanced logging tool provided on some of the images. It allows to emit loglines. For more info about WalT logging in general, see [`walt help show logging`](logging.md).

## Basic usage

You can run `walt-log-monitor` like this:
```
[node]$ walt-log-monitor <command...>
```

Output lines of `<command...>` (i.e. stdout and stderr) will be transmitted up to WalT server and stored as log lines associated with the log streams `<command>.<pid>.monitor`.

Most of the time, you could achieve a similar goal by typing the following:
```
[node]$ <command...> | walt-log-cat <command>.out
```

Or, if you want to catch stderr too:
```
[node]$ <command...> 2>&1 | walt-log-cat <command>.out
```

There is, however, a difference: `walt-log-monitor` will run `<command...>` in a virtual terminal. Therefore, `<command...>` should behave exactly the same whether you typed it directly or you prefixed with `walt-log-monitor`.
We wrote this tool because some commands act differently when then detect their output is not a terminal. For example, if `tcpdump` detects its output is a pipe (like in the `walt-log-cat` construct), it will bufferize its output differently. As a result, you may get different results whether you type the command alone or with the pipe plus `walt-log-cat` construct. On the contrary, it should act exactly the same if you prefix the command with `walt-log-monitor`.

## Installation

If your image does not provide `walt-log-monitor`, but it already provides python3.6+ and systemd, then you can get it by installing python package `walt-node`:
```
[image-shell]$ pip3 install walt-node
[image-shell]$ walt-node-setup
```

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

root@node1:~# walt-log-monitor tcpdump -l -i wlan0
tcpdump: verbose output suppressed, [...]
listening on eth0, link-type EN10MB [...]
10:57:58.4151 IP 10.8.1.3.85 > 10.8.1.1.56: [...]
10:57:58.4157 IP 10.8.1.1.56 > 10.8.1.3.85: [...]
[...]
```

And immediately log lines are catched on first terminal:
```
$ walt log show --realtime
12:57:58.300114 node1.tcpdump.514.monitor -> START
12:57:58.446818 node1.tcpdump.514.monitor -> tcpdump: verbose output suppressed, [...]
12:57:58.457552 node1.tcpdump.514.monitor -> listening on eth0, link-type EN10MB [...]
12:57:58.481478 node1.tcpdump.514.monitor -> 10:57:58.4151 IP 10.8.1.3.85 > 10.8.1.1.56: [...]
12:57:58.486306 node1.tcpdump.514.monitor -> 10:57:58.4157 IP 10.8.1.1.56 > 10.8.1.3.85: [...]
[...]
```
