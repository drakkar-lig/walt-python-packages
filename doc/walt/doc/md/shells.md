
# Shell usage notes

## Introduction

WalT users can use the following kinds of shell sessions:
* `walt node shell`
* `walt image shell`


Their purpose is very different.

## `walt node shell`: access to the real node

`walt node shell` just wraps a ssh session to the node.

Be warned that a WalT node is a very **volatile** environment. Each time a node reboots, it loses all modifications made on files (created, suppressed, modified), and restarts from the original files of the image it boots.
This ensures that a node booting a given image will always act the same.
(See [`walt help show node-bootup`](node-bootup.md) for a more technical explanation on this aspect.)

However, for convenience, a directory `/persist` is available on each node. Data stored there do remain available accross reboots.
You can use it to store large experiment results files for instance. `/persist` is a read-write NFS-mount: data is actually stored on the server.

## `walt image shell`: modification of operating system

If you want to modify files in a permanent way, you must modify the image the node boots. `walt image shell` is the most common way to do this. It provides a shell running in a virtual environment (docker container) where you can make the changes, such as installing packages for example.

Since the image is expected to be booted by a node, and the CPU architecture of the node may be different from the one of the server (e.g. ARM-based raspberry pi versus amd64-based server), the binaries found inside an image may not be compatible with the server CPU. In this case, any binary you run in this shell will involve **CPU emulation**, which leads to a slower behavior. Avoid heavy processing, such as compiling of a large source code base. In this case, cross-compiling on another machine and importing the build artefacts in the virtual environment (through the emulated network) should be the prefered option.
Also, keep in mind that in the virtual environment (docker container) no services are running (no init process, etc). Actually, the only process running in this virtual environment when you enter it is the shell process itself.

## Summary table

The following table summarizes usage of these 2 commands and their limits.

|                 | walt node shell        | walt image shell                            |
|-----------------|------------------------|---------------------------------------------|
| persistence     | until the node reboots | yes                                         |
| backend         | the real node          | virtual environment, possible CPU emulation |
| target workflow | testing/debugging      | apply changes                               |

