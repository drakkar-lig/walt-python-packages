
# Packaging notes

## Overview

This section exposes information useful when designing a walt package for a new Linux distribution.


## Change the default systemd service names

WalT server manages some services through systemd. You may specify the name of
these services in server configuration file.
Those values are optional, and defaults to the names used in Debian.
Currently, only the NFS server can be configured this way, because other services
are either run as a walt-specific service configuration, or have no interaction
with WalT server daemon.

The content of this file could be:
```
$ cat /etc/walt/server.conf
{
    "network": {
        # [...]
    },
    # Services configuration
    # ----------------------
    "services": {
        "nfsd": {
            "service-name": "nfs-kernel-server.service"
        }
    }
}
```
