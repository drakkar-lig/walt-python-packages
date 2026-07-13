# Synchronizing WalT nodes


Many IoT experiments require precise synchronization between nodes.
Several options are available, as shown below.

Computer clocks usually drift by several milliseconds per hour.
If your experiment needs precise clocks and lasts more than a few
tens of minutes, you should ensure that something will maintain
clock synchronization over time.

Note that if you need really precise clocks, you should avoid starting
your experiment just after the nodes have booted: let the synchronization
process converge at least a few minutes.


## PTP: Precision Time Protocol

The WALT server features a PTP service, so when a node boots a WALT OS
image equipped with a PTP daemon, its clock is precisely synchronized
with the server's clock. That is the case with default images of
Raspberry Pi boards for instance.

Note that the configuration file at `[image-root]:/etc/ptpd.conf` has
to indicate the network interface name used for synchronization,
e.g. `ptpengine:interface=eth0`.
Thus one has to ensure the network interface name will be correct
once the OS is started.
An option is to use a kernel flag `net.ifnames=0`, which will maintain
the old naming scheme (`eth0`, `eth1`, etc.).
On Raspberry Pi images, this flag can be added in the file at
`[image-root]:/boot/<model>/cmdline.txt`.


## NTP: Network Time Protocol

The WALT server also features an NTP service too, so another option is
to equip the WALT image with an NTP daemon. NTP is not as precise as PTP,
but there are more implementations. So considering a specific OS there is
more chance that you will find an NTP implementation readily available.

You will have to specify the WALT server IP address in
`[image-root]:/etc/ntp.conf`. In order to avoid binding your WALT image
with this specific parameter of your WALT platform, you should turn
`ntp.conf` into a "WALT image template file".
See [`walt help show image-from-scratch`](image-from-scratch.md) and look for the part
about "precise time synchronization".


## Generic synchronization

Independently of what the OS image contains, nodes always start to
communicate with the server to synchronize their clock, early in the
bootup procedure. This is a fallback mechanism useful when the OS image
does not provide a PTP or NTP daemon.

The first message round-trip allows to set the time of the node
with a worst-case precision of a few milliseconds.

If the `busybox` binary provided with the WALT image does not include
an `adjtimex` applet, then this generic synchronization process stops
there, and the clock of the node will start to drift (unless an NTP
or PTP daemon subsequently starts, of course).

If the `busybox` binary provides an `adjtimex` applet, then the process
will continue to adjust the clock, similarly to a PTP or NTP daemon.
After around one minute it will provide a sub-millisecond accuracy.
If an NTP or PTP daemon is subsequently started by the OS, the process
will detect it and stop.
