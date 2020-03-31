# Node bootup procedure

## Reminder about walt image structure

For details about walt image structure, checkout [`walt help show image-from-scratch`](image-from-scratch.md).

The following summarizes the important points regarding network boot handling.

In order to support several node models in WalT, we have to know which node model(s)
a given image supports. For example, some images may support only `rpi-2-b` and `rpi-3-b`
boards. Thus, every walt image must provide a docker label that indicates which models
this image can handle.

The image must also provide a directory `/boot/<model>` for each model. This directory
contains the boot files needed (see bootup steps below).

## Bootup steps

The following applies to a raspberry pi node.
However, PC nodes boot very much the same, except that:
- the bootloader is iPXE instead of u-Boot
- the SD card is usually replaced by a USB device

Here are the bootup steps for a raspberry pi:
1.  The board is powered on and starts its firmware
2.  The firmware starts u-boot as a 2nd stage bootloader stored on the SD card
3.  u-boot starts the 1st stage script stored on the SD card
4.  if needed, the script analyses environment variables (cpu model, etc.) in order to
    detect the exact model (e.g. `rpi-3-b`).
5.  u-boot runs its DHCP client procedure in order to get its IP address and the
    address of the TFTP server (i.e. the walt server), or reboots if it fails.
    The model of node is passed to the DHCP server by using the VCI field (vendor class
    identifier) or UCI (user class identifier) of the DHCP request.
    The VCI is set on u-boot side by a line such as `setenv bootp_vci walt.node.<model>`.
6.  The DHCP server (on the walt server) has a hook allowing to detect a lease has been
    delivered. When this happens, a tool called `walt-dhcp-event` is run (with mac, ip,
    vci and uci as parameters).
    This allows to send a node registration request to `walt-server-daemon`.
7.  If the node is new:
    1.  `walt-server-daemon` ensures the default image for this model of node is downloaded.
        (This step may last a long time if it involves downloading an image from the docker
        hub.)
    2.  If needed, it mounts the image at `[image_root] = /var/lib/walt/images/<image_id>/fs`
        and adds a few walt-specific files (e.g. `/bin/walt-init` and associated boot scripts,
        public key authentification files for passwordless ssh connection on node, etc.)
    3.  It creates several symlinks (see note 1 for details):
        -   `/var/lib/walt/nodes/{ip_address}/fs` -> `[image_root]`
        -   `/var/lib/walt/nodes/{ip_address}/tftp` -> `[image_root]/boot/<model>`
8.  u-boot downloads and executes the second stage script at `tftp:/start.uboot`. The tftp
    server actually remaps this to `/var/lib/walt/nodes/{ip_address}/tftp/start.uboot` thanks
    to a mapping rule. And this actually targets `[image_root]/boot/<model>/start.uboot` thanks
    to the 2nd symlink above. If the TFTP request fails (supposedly the walt image is not ready
    yet), the node reboots. Having such a second boot stage script stored on the image allows
    to update the boot procedure for specific needs (adding a kernel parameter, etc). The rest
    of the procedure is handled by this script.
    We list below the steps that are performed by our default raspberry pi image, for instance.
9.  u-boot tries to load `tftp:/kernel` (mapped to `[image_root]/boot/<model>/kernel`), or
    reboot if it fails;
10. u-boot tries to load `tftp:/dtb` (mapped to `[image_root]/boot/<model>/dtb`), or reboot if
    it fails;
11. u-boot starts the kernel, with the following kernel options (and more)
    `init=/bin/walt-init root=/dev/nfs nfsroot=<server_ip>:/var/lib/walt/nodes/{ip_address}/fs,nfsvers=3`
12. the kernel starts, mounts the NFS share and then calls `/bin/walt-init`
13. walt-init starts the NFS watchdog process (to periodically check that the NFS share is
    accessible and reboot otherwise)
14. walt-init starts the network service process (to perform soft-reboot requests sent by the
    server)
15. walt-init starts the bootup notification process. This process waits for port localhost:22 to
    be opened (since all walt images must provide a ssh server process) and then sends a bootup
    notification to the server.
16. walt-init runs `walt-clock-sync` to ensure an initial clock synchronization with the server
    (for more precise clock synchronization, the image should provide a PTP daemon)
17. walt-init mounts a union of the NFS root and a virtual filesystem in RAM (see note 2)
18. walt-init calls `/sbin/init` (the regular OS init system, such as systemd) in a chroot on
    top of the union
19. the walt image OS starts up

Notes and details:
1.  Actually, in directory `/var/lib/walt/nodes`, several entries are created for each node,
    all pointing to the same structure described above. The `{mac_address}` is also present
    in two forms, together with the `{ip_address}` entry. This allows to deal with the
    limitations of the bootloaders and TFTP server remapping syntax.
2.  This union of the NFS root and a virtual filesystem in RAM is a very important feature.
    It allows:
    - to keep the NFS share read-only (allowing several nodes booting the same image to
      modify files would obviously cause problems).
    - to avoid writing files on the SD card, thus keep it read-only, which greatly extends its
      lifetime.
    - to discard any file modification each time the node reboots, ensuring a high level of
      reproducibility: as long as the user keeps the same image, the node will boot exactly
      the same files.
