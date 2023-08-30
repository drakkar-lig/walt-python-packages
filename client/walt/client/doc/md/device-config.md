
# Updating configuration settings about devices

WalT allows users to show or modify device configuration settings by using commands `walt device config` or `walt node config`.
For instance:
```
$ walt device config switch1                    # show
$ walt device config switch1 lldp.explore=true  # modify
$ walt node config virt-node ram=384M           # modify
```

One may also show or change several settings at once, and/or show or update them on several devices at once. (See also: [`walt help show device-sets`](device-sets.md))
For instance:
```
$ walt device config all-switches               # show
$ walt device config all-switches lldp.explore=true poe.reboots=true
$ walt node config virt-node-1,virt-node-2 ram=384M
```

However, in some cases, the semantic of a particular setting may restrict syntax.
For instance, the `expose` setting can only be applied to a single device at once,
because it would otherwise mean redirecting a single server TCP port to several devices,
an impossible operation.

You can also use this command to indicate to walt server that an unknown device is actually a switch:
```
$ walt device config unknown-a2f2d3 type=switch
```

Here is the set of settings currently allowed:

| Name           | possible values         | Applies to:         | Notes |
|----------------|-------------------------|---------------------|-------|
| lldp.explore   | true or false           | switches            | (1)   |
| poe.reboots    | true or false           | switches            | (1)   |
| snmp.version   | 1 or 2                  | switches            | (1)   |
| snmp.community | e.g. 'private'          | switches            | (1)   |
| type           | 'switch'                | 'unknown' devices   | (2)   |
| netsetup       | 'NAT' or 'LAN'          | devices of walt-net | (3)   |
| ram            | e.g. '384M' or '1G'     | virtual nodes       |       |
| cpu.cores      | e.g. 1 or 4             | virtual nodes       |       |
| disks          | e.g. '8G' or '32G,1T'   | virtual nodes       |       |
| networks       | e.g. 'walt-net,ext-net' | virtual nodes       | (4)   |
| kexec.allow    | true or false           | nodes               | (5)   |
| expose         | e.g. '80:8080,443:8443' | devices of walt-net | (6)   |

Notes:
1. See [`walt help show switch-install`](switch-install.md)
2. Only allowed when changing device type from 'unknown' to 'switch'
3. See [`walt help show device-netsetup`](device-netsetup.md)
4. See [`walt help show vnode-networks`](vnode-networks.md)
5. Default is true: allow kexec-rebooting if the optional script `[walt-image]:/bin/walt-reboot` implements it.
6. See [`walt help show device-expose`](device-expose.md)
