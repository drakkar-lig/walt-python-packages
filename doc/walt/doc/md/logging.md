
# How to use WalT logging system

## Introduction

WalT provides a subsystem to save and query experiment logs. This page describes how this subsystem works and how to use it.

Let's start with some basic notions:
* A **logline** is a line of text transmitted from a node to the server, and then to any client that would query it.
* A **timestamp** and an **issuer** (the device that emitted it, i.e. a node or the server) is associated with each logline.
* A **logstream** is a subset of loglines. Logstreams have a name, which can be used to filter logs easily.

All loglines and logstreams are saved in a database on the server.

Two kinds of logs exist:
* Platform-generated logs
* Experiment logs


## Platform logs

The platform generates log lines by itself when an important event occurs, or for debugging purpose.

For instance, the following command displays log lines in realtime when an important event occur:
```
$ walt log show --realtime --platform
```

This other example fetches and displays walt server daemon logs generated during the 5 last minutes:
```
$ walt log show --history -5m: --server
```


## Experiment logs

WalT will not generate experiment logs by itself. However, all WalT nodes provide tools you can use in order to emit loglines while your experiment is running. For example, you could write an experiment script `experiment1.sh` such as:
```bash
#!/bin/bash

init_exp()
{
    [...]
}

measure()
{
    logstream="$1"
    measure_index="$2"
    [...]
    result=[...]
    walt-log-echo $logstream "measure $measure_index -> $result"
}

# init
init_exp
logstream="exp1-$(hostname)"

# start
walt-log-echo $logstream "Experiment 1 started."

# loop many times for statistical soundness
for i in $(seq 1000)
do
    measure $logstream $i
done

# end
walt-log-echo $logstream "Experiment 1 ended."

```

As you may guess, running this script on a node `rpi2` would generate a logstream called `exp1-rpi2` and made of 1002 loglines.

All WalT nodes provide at least the following tools:
* `walt-log-echo` (see [`walt help show log-echo`](log-echo.md))
* `walt-log-cat`  (see [`walt help show log-cat`](log-cat.md))
* `walt-log-tee`  (see [`walt help show log-tee`](log-tee.md))

Do not hesitate to check their respective help page.
These tools are actually copied by the server, before an image is made accessible to nodes through TFTP and NFS. This ensures that these tools will always be available on nodes.

Another tool is provided on a subset of WalT images:
* `walt-log-monitor`  (see [`walt help show log-monitor`](log-monitor.md))

This one is not always available because it is based on a python package and systemd, and some minimal images may not provide python3 or systemd. See [`walt help show log-monitor`](log-monitor.md) for installing it when it is missing.

## How to query / display / work with experiment logs

The main entrypoint to display experiment logs is subcommand `walt log show` (see [`walt help show log-show`](log-show.md)).

Depending on what you want to achieve, you may get more information in the following help pages:

* Retrieving past logs: [`walt help show log-history`](log-history.md)
* Printing logs in real time: [`walt help show log-realtime`](log-realtime.md)
* Updating log display format: [`walt help show log-format`](log-format.md)
* Filtering log issuers: [`walt help show log-issuers`](log-issuers.md)
* Synchronizing a script based on logs: [`walt help show log-wait`](log-wait.md)
* Using log checkpoints: [`walt help show log-checkpoint`](log-checkpoint.md)
