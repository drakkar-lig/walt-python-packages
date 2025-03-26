# WalT VPN Security notes

## HTTP protocol usage

The early bootup steps of a WalT VPN node rely on the
Raspberry Pi 5 HTTP boot feature.

In this boot mode, the board downloads a FAT image containing
boot files such as a Linux kernel and an init ramdisk (initramfs).
The HTTP request targets the VPN HTTP entrypoint, which redirects
to the WalT server.
This FAT image is signed by the WalT server and the board verifies
this signature thanks to the server public key stored in its EEPROM.

The FAT image does not contain any secrets, so the fact HTTP is
a clear-text protocol is not a problem.


## SSH protocol usage

In the initramfs bootup phase, an SSH connection is made to the
WalT server (possibly passing through the SSH entrypoint acting
as a proxy).
Authentication of the node is based on an SSH certificate
established when the node first registered, and stored in its
EEPROM.
Authentication of the server is based on SSH entrypoint host keys,
also retrieved when the node first registered, and stored in its
EEPROM.

This SSH connection then serves as a tunnel, with one virtual
network interface at each end, and the node continues with the
usual WalT network boot procedure through this tunnel.


## VPN Boot modes

The Raspberry Pi boards do not include a secure element, so
the VPN secrets are left readable in their EEPROM. To prevent
unauthorized people to read those secrets and use them to
breach the WalT VPN, WalT OS images of VPN nodes are designed
to only allow a remote login from the WalT server. So the secrets
are only readable by WalT users.

However, if unauthorized people can access a board physically,
they could try to make it boot another OS, and bypass this
security measure. The "VPN boot mode" setting, accessible in the
server setup screens (i.e., `walt-server-setup --edit-conf`),
can be set to "enforced" to solve this issue.

This setting actually defines which boot procedures are allowed
for VPN nodes:
* enforced: only allow the VPN boot procedure. Recommended when
  VPN nodes are installed in public places.
* permissive: try the VPN boot procedure; if this fails, try an
  unsecure TFTP boot (e.g., this allows a board to boot after it
  was moved to another WalT platform), and if this fails too, try
  to boot an OS from the SD card.

On bootup, VPN nodes automatically reflash their EEPROM to reflect
a change of this setting.

Even if "enforced" mode was selected, it is always possible to
reinitialize the EEPROM of a board, by using an SD card and the
archive called `rpi-5-sd-recovery.tar.gz`.
See [`walt help show node-install`](node-install.md).
After such a reinitialization, the EEPROM is obviously free of any
VPN secrets, and the board is ready to register again as a WalT VPN
node.


## Revoking an SSH certificate

As explained in the previous section, stealing a node deployed in a
public place and booting it elsewhere should not be enough to read
the VPN secrets.

However, as an additional security measure, we propose to revoke the
SSH certificate of the node in this case.

For this purpose, run `walt-vpn-admin` as user `root` on the
WalT server and select the appropriate menu entry.
