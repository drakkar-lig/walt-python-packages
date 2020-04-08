
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
$ walt device config all-switches lldp.explore=true poe.reboot=true
$ walt node config virt-node-1,virt-node-2 ram=384M
```

You can also use this command to indicate to walt server that an unknown device is actually a switch:
```
$ walt device config unknown-a2f2d3 type=switch
```

Here is the set of settings currently allowed:

| Name           | possible values        | Applies to:       | Notes |
|----------------|------------------------|-------------------|-------|
| lldp.explore   | true or false          | switches          | (1)   |
| poe.reboots    | true or false          | switches          | (1)   |
| snmp.version   | 1 or 2                 | switches          | (1)   |
| snmp.community | e.g. 'private'         | switches          | (1)   |
| type           | 'switch'               | 'unknown' devices | (2)   |
| netsetup       | 'NAT' or 'LAN'         | nodes             | (3)   |
| ram            | e.g. '384M' or '1G'    | virtual nodes     |       |
| cpu.cores      | e.g. 1 or 4            | virtual nodes     |       |

Notes:
1. See [`walt help show switch-install`](switch-install.md)
2. Only allowed when changing device type from 'unknown' to 'switch'
3. See [`walt help show node-netsetup`](node-netsetup.md)
