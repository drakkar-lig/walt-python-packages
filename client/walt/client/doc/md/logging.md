
# How to use WalT logging system

## Introduction

WalT provides a subsystem to save and query experiment logs. This page describes how this subsystem works and how to use it.

Let's start with some basic notions:
* A **logline** is a line of text transmitted from a node to the server, and then to any client that would query it.
* A **timestamp** and a **sender** (the WalT node that emitted it) is associated with each logline.
* A **logstream** is a subset of loglines. Logstreams have a name, which can be used to filter logs easily.

All loglines and logstreams are saved in a database on the server.

## How to generate experiment logs

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

This one is not always available because it is based on a python package, and some minimal images may not provide python. In order to install it in your own images, if it is missing, you can use `pip install walt-node`.

## How to query / display / work with experiment logs

The main entrypoint to display experiment logs is subcommand `walt log show`.

Depending on what you want to achieve, checkout the appropriate help page in the following list.

* Retrieving past logs: [`walt help show log-history`](log-history.md)
* Printing logs in real time: [`walt help show log-realtime`](log-realtime.md)
* Updating log display format: [`walt help show log-format`](log-format.md)
* Synchronizing a script based on logs: [`walt help show log-wait`](log-wait.md)
* Using log checkpoints: [`walt help show log-checkpoint`](log-checkpoint.md)
