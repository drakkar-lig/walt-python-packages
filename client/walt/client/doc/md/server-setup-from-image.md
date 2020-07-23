
# Walt server setup from USB image

## Overview

These are the steps you should follow to install a walt server machine using the USB image we provide.


## Booting the machine using WalT server image

* Download the OS image `server-install-prod.dd.bz2` from https://github.com/drakkar-lig/walt-project/releases/latest.
* Uncompress and dump it to your USB drive (assuming a linux-based machine, and your USB disk at `/dev/sdX`):
  `$ bzcat server-install-prod.dd.bz2 | dd of=/dev/sdX bs=10M; sync; sync`
* Boot the server machine using the flash drive (by configuring BIOS/UEFI boot settings accordingly).
* When asked, enter the root OS password you want to set on this server.
* When OS is booted, you can login with user `root` and the password you just specified.

Once this procedure is done, you should return to server install procedure [`walt help show server-install`](server-install.md)
for the remaining configuration and testing.


## Move the OS to the main disk

Over time, a walt server needs more disk space to store walt images.
So you probably want to migrate the server operating system from the USB flash drive to the server's internal disk.

This can actually be done at any time by running the following script:
```
$ /opt/debootstick/live/init/migrate-to-disk.sh
```

The procedure is completely transparent: the system will continue working while it runs.
When done, you can remove the USB flash drive (no need to reboot).

Note: the OS is moved, not copied. Thus the USB flash drive cannot be used right away to
install another server. You should flash it again in this case.

