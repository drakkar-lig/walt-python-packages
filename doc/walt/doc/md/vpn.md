# How to use WalT built-in VPN and distant nodes

## Introduction

WalT provides a built-in VPN subsystem allowing to deploy distant nodes.
This feature is particularly useful when experimenting with long-range protocols.

Obviously, this feature applies to static network environments, not to a mobile WalT platform.

The WalT VPN is based on **HTTP** and **SSH** protocols, which allow an easy integration in existing infrastructures.

Let's start with some important notes and vocabulary:
* VPN nodes can reach the WALT server by traversing HTTP and SSH proxies. These proxies are called **HTTP entrypoint** and **SSH entrypoint**.
* The WalT server itself can be used as a VPN entrypoint, both for HTTP and SSH. Unless the hostname configuration is wrong on the WalT server machine, `walt-server-setup --edit-conf` proposes this default configuration when enabling the VPN feature.


## Typical setups

With the default configuration of a WalT server, nodes can only be connected on the dedicated platform network, called `walt-net`:

```
           ---------------
          |  WalT server  |            gateway to internet
           ---|------|----                     |
      walt-net|      |company/lab network      |
              |       -------------------------
              |
      -----------------
     |        |        |
  ------   ------   ------
 |Node 1| |Node 2| |Node 3|
  ------   ------   ------
```

For enabling the VPN one must run `walt-server-setup --edit-conf` and use the corresponding menu entry on the VPN configuration screen.

Unless the domain name configuration is wrong, the WalT server itself is proposed to serve as a VPN entrypoint.
So unless SSH or HTTP are filtered by this company/lab network, nodes 4 and 5 of the following figure can now use the VPN booting procedure and boot as WalT nodes too.

```
           ---------------
          |  WalT server  |            gateway to internet
           ---|------|----                     |
      walt-net|      |company/lab network      |
              |       -------------------------
              |                       |
      -----------------            --------
     |        |        |          |        |
  ------   ------   ------     ------   ------
 |Node 1| |Node 2| |Node 3|   |Node 4| |Node 5|
  ------   ------   ------     ------   ------
```

Usually, the WalT server is not directly reachable from the Internet. However, as a second step, one can extend the scope of the VPN by configuring a machine reachable from the internet as the entrypoint, as shown in the next figure.

```
           ---------------                        ------------
          |  WalT server  |                      | Entrypoint |
           ---|------|----                        ------------
      walt-net|      |       company/lab network    |     |
              |       ------------------------------    [...] internet
              |                       |                  | |
      -----------------            --------            --   ---
     |        |        |          |        |          |        |
  ------   ------   ------     ------   ------     ------   ------
 |Node 1| |Node 2| |Node 3|   |Node 4| |Node 5|   |Node 6| |Node 7|
  ------   ------   ------     ------   ------     ------   ------
```

This allows to deploy nodes 6 and 7 in much more distant places.


## How to setup a VPN node

For now, the VPN feature is limited to Raspberry Pi 5B boards only.

As soon as the VPN is enabled on server side, the node enrollment procedure is fully automated: on the first boot in the WalT network, Raspberry Pi 5B boards automatically become VPN-capable nodes.

For instance, if "Node 3" of the figure is a Raspberry Pi 5, then after the first boot one can reconnect it next to "Node 5" or "Node 7", and it will just work.


## Performance note

Distant nodes can be much slower than local ones. The performance impact is nearly proportional to the network latency between the server and the node.

Since nodes are booting their OS image over the network, reading files and directories require network requests to the server. However, excluding RAM intensive scenarios, the OS should be able to keep the response data in memory and avoid sending twice the same requests. Therefore, the first shell session after startup may be very slow for example, while the second and subsequent ones should be much faster.
The boot delay can also be quite long.


## How to setup a VPN entrypoint

Setting up a VPN entrypoint is a two-steps process:
1. Configure a machine as a proxy (HTTP or SSH or both);
2. Change WalT VPN configuration by running `walt-server-setup --edit-conf`.

The VPN nodes already deployed will automatically take the change into account.

See [`walt help show vpn-http-entrypoint`](vpn-http-entrypoint.md) and [`walt help show vpn-ssh-entrypoint`](vpn-ssh-entrypoint.md) for the details.


## Enforced vs permissive VPN boot modes

The VPN server setup screen, accessible by running `walt-server-setup --edit-conf`, proposes another setting called `VPN boot mode`. It defines which boot procedures are allowed for VPN nodes.

Two values are possible:
* enforced: only allow the VPN boot procedure. Recommended when
  VPN nodes are installed in public places.
* permissive: try the VPN boot procedure; if this fails, try an
  unsecure TFTP boot, and if this fails too, try to boot from the
  SD card.

See [`walt help show vpn-security`](vpn-security.md) for more info.

This choice can be reverted at any time by returning again to
the server setup screens (i.e., `walt-server-setup --edit-conf`).

On bootup, VPN nodes automatically reflash their EEPROM to
reflect changes in VPN settings.

Even if "enforced" mode was selected, it is always possible to
reinitialize the EEPROM of a board, by using an SD card and the
archive called `rpi-5-sd-recovery.tar.gz`.
See [`walt help show node-install`](node-install.md).
