
# Configuring secondary networks on virtual nodes

By default virtual nodes have one single network interface.
Obviously, this network interface is linked to `walt-net`, i.e. the network of the WALT platform.

However, this default configuration may be changed if needed:
* secondary networks may be defined;
* optional network resource limits may be applied (i.e. to simulate a higher latency or lower bandwidth).

For instance, here is how we can create a secondary network `home-net` accessible to our virtual nodes
`vnode1` and `vnode2`:

```
$ walt node config vnode1,vnode2 networks=walt-net,home-net
```

After rebooting, `vnode1` and `vnode2` will get one more emulated network interface,
allowing them to reach each other through a new network `home-net`.
Unlike `walt-net`, this kind of secondary network is left unmanaged be the WALT platform,
and it is the responsability of the walt user to configure the nodes appropriately.
For instance, the relevant WALT images may be edited in order to let OS startup scripts
assign static IP addresses. Or one of the nodes may be configured to start a DHCP service
on its new interface.

A virtual node may even define more than two networks if needed (e.g. `networks=walt-net,net-a,net-b,net-c`).
However, referencing `walt-net` is mandatory (this is obviously needed for proper operation as a WALT node).
Thus the default configuration for newly created virtual nodes is just `networks=walt-net`.

Network resource limits may be applied by using this kind of syntax:

```
$ walt node config vnode1 networks=walt-net,home-net[bw=100Mbps,lat=10ms]
```

Bandwidth unit may be `Mbps` (megabit per second) or `Gbps` (gigabit per second).
Latency unit may be `ms` (millisecond) or `us` (microsecond).

Here `vnode1` will have its connexion to `home-net` limited to 100Mbps, and a round-trip latency of 10ms
will be observed. Note that the bandwidth limitation applies to download traffic only.

Also note that applying this configuration to both `vnode1` and `vnode2` will result in:
* a bandwith limit at 100Mbps applied on both ways
* a round trip latency of 20ms

Another important remark is that depending on your hardware, the WALT server OS may not be
able to achieve a very low latency value or a very high bandwidth value.

For all these reasons, it is recommended to test this kind of setup by using tools such as
`ping` and `iperf3`. These tools may not be present by default in the WALT image, but they
are easy to install.

As a side note, it is even possible to apply network resource limits to `walt-net` connexion,
if ever this is needed. However, this may severely impact the performance of the node
(such as the time for the network boot to complete).
