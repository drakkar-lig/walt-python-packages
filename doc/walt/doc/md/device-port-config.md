
# Viewing and updating switch ports configuration

Users can view or modify switch ports configuration using command `walt device port-config`:
```
$ walt device port-config switch1                   # show conf of all ports of switch1
[...]

$ walt device port-config switch1 4                 # show conf of 4th port of switch1
Port 4 of switch1 has the following config:
4: name="4" poe=on peer=walt-server

$ walt device port-config switch1 4 name="SR32C14"  # rename port 4 of switch1
Done.

$ walt device tree                                  # name is updated in the network view
-- switch1 --
 ├─SR32C14: walt-server
[...]
```

When the WalT network is deployed on selected wall plugs of a large building, and these wall plugs have their name on a tag, one can give to switch ports the name of respective wall plugs, for easier platform maintenance.

WalT implements the following port settings:

| Name      | possible values         | access type    |
|-----------|-------------------------|----------------|
| name      | alphanumeric name       | read-write     |
| poe       | on / off / unavailable  | read           |
| peer      | peer device or unknown  | read           |

