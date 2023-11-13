
# Rebooting WalT nodes

## Introduction

In its default mode of operation (1), WalT helps reproducibility by ensuring exactly the same OS files
are used at each reboot of a node. The files are those of the WalT image, which always remains read-only (2).
Consequently, most WalT users just use a WalT image modified to trigger an experiment script on bootup
(e.g., by adding a systemd service), and then rebooting the node(s) as many times as needed for statistical
soundness. Thus the reboot operation is very important in WalT.

Notes:
(1) Recently, WalT introduced another mode of operation called hybrid-boot, which does not provide the same
guarantee, but may be used when the default network boot procedure is not suitable.
Check-out [`walt help show boot-modes`](boot-modes.md) for more info.
(2) One notable exception to this fact is directory `/persist`, where one can store data files which must be
preserved across reboots.


## walt node reboot

The command `walt node reboot <node>` (or `walt node reboot <node-set>`) allows to reboot a node (or a set
of nodes).

This command first tries a "soft-reboot", i.e., sends a REBOOT request on TCP port 12346 of the node.
If the node fails to acknowledge the request, a "hard-reboot" is done if possible, or an error is printed.

Hard-rebooting a virtual node consists of killing the virtual machine process, and is always possible.
Hard-rebooting physical nodes is possible when they are powered with Power-Over-Ethernet and config option
`poe.reboots` is enabled on the switch (cf. [`walt help show device-config`](device-config.md)). If not,
an error is printed.

It is possible to force a "hard-reboot", without trying a "soft-reboot" first, by using option `--hard`.
This can be useful if ever the "soft-reboot" is not enough (e.g., power-cycling the whole raspberry pi
board might be needed to recover proper operation of a buggy USB device).


## Notes about reboot procedures

Bootup procedures are implemented differently based on the current boot mode of the node.
Check-out [`walt help show boot-modes`](boot-modes.md) for more info about boot modes.


### Network boot mode

In this default mode of operation, the node stacks two filesystem layers:
- at the bottom, the WalT image is mounted as a read-only network filesystem;
- at the top, a read-write layer is mounted in the RAM of the node.
All created files and file modifications will be handled by the read-write layer, which means in the RAM
of the node, and cleared up when the node reboots (which ensures reproducibility at each reboot).
As a side effect of these RAM-only modifications, `walt node reboot` does not bother shutting down the
OS services properly in this case, even if we call it a "soft-reboot": it calls the bare
`busybox reboot -f` command directly, allowing for faster reboots.

WalT provides a way for users to alter this reboot procedure: they may provide an executable file
`/bin/walt-network-reboot` (`/bin/walt-reboot` is accepted too for backward compatibility) in the
WALT image. In this case, this executable will be executed instead of the bare `busybox reboot -f`
command for soft-rebooting. This can be used for implementing an optimized reboot procedure, such
as using `kexec` and avoiding long hardware reboot delays on server-class nodes. The default images
we provide for pc-x86-64 and pc-x86-32 machines are equipped with such a hook for kexec rebooting.

One notable exception is virtual nodes, which will never use this custom executable for rebooting,
even if present. In fact, rebooting virtual nodes is already fast: obviously, it does not involve
real hardware intialization. Moreover, just using kexec would prevent real restarts of the virtual
machine process, whereas such restarts are needed when changing virtual node configuration settings
(e.g., adding a new disk or network interface).

On physical nodes, `/bin/walt-network-reboot` may also fallback to the bare `busybox reboot -f`
command if you configured a node with `kexec.allow=false`.


### Hybrid boot mode

In this alternative mode of operation, i.e., **hybrid boot mode**, the node has a copy of WalT image
contents on a local disk. See [`walt help show boot-modes`](boot-modes.md) for more info.
In this mode, "soft-reboots" may take a little more time, because OS services will be properly shut
down.

Similarly to the network boot mode, users may provide an executable file `/bin/walt-hybrid-reboot`
to implement optimized reboot procedures in the hybrid boot mode. The restrictions regarding
virtual nodes and the configuration option `kexec.allow=false` also apply here.
