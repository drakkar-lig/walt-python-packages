# WALT VPN node (Raspberry Pi 5B) boot — diagrams

These diagrams describe how a WALT VPN-capable Raspberry Pi 5B boots, how the
server prepares and exposes the boot material, and how an RPi5 gets enrolled as
a VPN node.

Key source references (WALT server):
- `server/walt/server/mount/setup.py` → `generate_boot_sig()`, `setup()`
- `server/walt/server/exports/exports.py`, `server/walt/server/exports/ops/mounts.py`
- `server/walt/server/processes/main/network/tftp.py`
- `server/walt/server/services/httpd/httpd.py`
- `server/walt/server/processes/main/vpn.py` → `enrollment()`
- `server/walt/server/setup/vpn.py`
- doc: `doc/walt/doc/md/vpn-security.md`, `vpn.rst`, `node-bootup.md`

The *OS-image* side of the mechanism (enrollment service, `boot.img`
maintenance) is covered in the `walt-images` build tree (section 6).

---

## 1. Deployment context

A WalT server runs on the local "walt-net" LAN. A VPN-capable RPi5 node may be
located in that same LAN, or physically moved to a distant site and connected
through the Internet / a corporate network. In the latter case the node does
not reach the WalT server directly: it goes through small, hardened
**entrypoints** (HTTP and SSH), which forward traffic into the walt-net.

Read from left to right: node → entrypoints → server.

```mermaid
flowchart LR
    subgraph NODES["WalT nodes"]
        Nlocal["RPi5 on local walt-net<br/>(VPN-capable or not)"]
        Nvpn["RPi5 VPN node<br/>in a distant / moved site"]
    end

    subgraph EP["Entrypoints (optional, for distant nodes)<br/>HTTP and SSH entrypoints may be the<br/>same machine or different machines"]
        EP_HTTP["HTTP entrypoint<br/>exposes / proxies the boot files"]
        EP_SSH["SSH entrypoint<br/>SSH tunnel endpoint into walt-net"]
    end

    subgraph SRV["WalT server (on walt-net)"]
        SRV_BOX["WalT server<br/>walt-server-daemon / httpd<br/>DHCP / TFTP / NFS<br/>VPN CA + HTTP boot RSA-2048 keys"]
    end

    Nvpn -->|"HTTP 80: firmware HTTP boot<br/>(fetch boot.img + boot.sig)"| EP_HTTP
    Nvpn -->|"SSH 22: VPN tunnel<br/>(for the WalT network boot)"| EP_SSH
    EP_HTTP -->|"HTTP"| SRV_BOX
    EP_SSH -->|"SSH (tunnel)"| SRV_BOX
    Nlocal -.->|"direct, inside walt-net<br/>(TFTP / NFS, and HTTP / SSH)"| SRV_BOX
```

### Only the *start* of the boot differs

Whether the node is a VPN node or not, once its OS is running the boot
procedure is identical (NFS root, `/bin/walt-init`). Only the very beginning —
how the kernel and initramfs are fetched and how the node reaches the walt-net —
differs:

```mermaid
flowchart LR
    A["Classical (non-VPN) node or<br/>not-yet-enrolled RPi5"] -->|"TFTP boot<br/>(firmware)"| C["WalT network boot<br/>(NFS root, /bin/walt-init)"]
    B["Enrolled VPN node"] -->|"HTTP boot of boot.img + boot.sig,<br/>then SSH tunnel to walt-net"| C
```

### Raspberry Pi firmware boot methods — no ipxe

We make no use of ipxe here (ipxe is only used by pc-x86-64 WalT nodes). For the
RPi5 we simply rely on the boot methods built into the Raspberry Pi firmware
(publicly documented):

- **SD-card boot** — used to recover a board;
- **TFTP boot** — used for the classical, non-VPN WalT boot procedure of an RPi5
  on the walt-net;
- **HTTP boot** — used once the RPi5 is enrolled as a VPN node.

HTTP boot requires the server to serve two files, `boot.img` and `boot.sig`:

- `boot.img` is a **FAT-formatted file archive** that contains the same kind of
  files a Raspberry Pi finds on its SD card (kernel, initramfs, config, ...).
  Because it is only fetched over HTTP, it **must contain no secret**.
- `boot.sig` is the RSA signature of `boot.img`, produced by the WalT server
  with the private HTTP boot key. The board verifies it with the corresponding
  public key stored in its EEPROM.

---

## 2. Boot files: prepared, signed, and served

One OS image is used for all RPi models it supports. For an RPi5 to boot over
HTTP, the image's boot directory must contain `boot/rpi-5-b/boot.img` (a FAT
archive) and a `boot.sig` (its signature). This section shows how the WALT user,
the server daemon, the server httpd, and the WALT node interact to prepare,
sign, and serve these two files.

```mermaid
sequenceDiagram
    autonumber
    participant U as "WALT user"
    participant D as "WALT server daemon"
    participant H as "WALT server httpd"
    participant N as "WALT node (RPi5)"

    U->>D: trigger image mount<br/>(e.g. walt node boot <node> <image>)
    Note over D: mount the OS image, run image setup<br/>(other steps: walt scripts, ssh keys,<br/>symlinks, timezone, ...)
    Note over D: check image boot dir: manage boot.img + boot.sig<br/>(boot.img is expected to be in the image, boot.sig<br/>is produced by the server if missing)
    D->>D: generate_boot_sig(): sign boot.img with the<br/>HTTP boot private key, write boot.sig
    D->>H: expose the image boot dir to serve (<id>/path)
    Note over N: later, at node boot time: the RPi5 firmware<br/>HTTP-boots and fetches boot.img + boot.sig
    N->>H: GET /walt-vpn/per-ip/<ip>/boot.img
    N->>H: GET /walt-vpn/per-ip/<ip>/boot.sig
    H-->>N: boot.img + boot.sig
```

Notes:

- The signature is computed **once when the image is mounted** and stored as a
  static `boot.sig` next to `boot.img` (`generate_boot_sig()`,
  `mount/setup.py`). The firmware does not re-sign; it only verifies.
- The HTTP boot keys are an RSA-2048 key pair at
  `/var/lib/walt/http-boot/private.pem` + `public.pem` (generated by the
  server; see `const.py`). `public.pem` is what the board ultimately stores in
  its EEPROM to verify `boot.sig`.
- The `boot.img` FAT file itself is maintained by the **OS image** (see
  section 6), not by the server. The server only signs whatever `boot.img` is
  present.

---

## 3. First boot of an RPi5 and VPN enrollment

For an RPi5 to become a VPN-capable node it must be booted **at least once on
the walt-net** using the classical (non-VPN) WalT boot procedure. Being
*inside* the walt-net is what lets it reach the server and complete
enrollment.

Please note: before enrollment, the node **is not able to HTTP-boot**. Like any
non-VPN-capable board, it starts by **TFTP booting** from the walt-net.

To prepare a brand-new board, one first flashes it (e.g. with the WalT
SD-card recovery image). Doing so **resets the board's EEPROM boot order**,
enabling the **TFTP boot** method, so the board can boot using the classical
WalT boot procedure from the walt-net.

```mermaid
sequenceDiagram
    autonumber
    participant BOARD as "RPi5 board<br/>(firmware + EEPROM)"
    participant IM as "initramfs<br/>(from image boot files)"
    participant OS as "OS image<br/>(runs /bin/walt-init,<br/>then the auto-enroll service)"
    participant S as "WALT server daemon<br/>(+ all server-side parts)"

    Note over BOARD: SD recovery image was used to flash the EEPROM:<br/>boot order enables TFTP boot
    BOARD->>IM: TFTP boot (classical, non-VPN):<br/>fetch kernel + initramfs over walt-net
    IM->>IM: boot kernel with root=/dev/nfs
    IM->>S: NFS mount the root filesystem (walt-net)
    IM->>OS: /bin/walt-init (classical WalT boot)
    OS->>OS: OS boots normally

    Note over OS: the image provides a systemd service,<br/>walt-vpn-auto-enroll, started at OS boot
    OS->>OS: read current EEPROM values (entrypoint, boot mode, vpn mac)
    OS->>S: GET node-conf (ssh/http entrypoint,<br/>boot mode, vpn mac) over http://server.walt
    OS->>OS: generate an SSH keypair
    OS->>S: POST /walt-vpn/enroll (ssh-pubkey)
    S->>S: sign the node SSH pubkey with the VPN CA,<br/>allocate the node vpn MAC
    S-->>OS: ok
    OS->>S: GET node-conf/ssh-pubkey-cert, ssh-entrypoint-host-keys,<br/>public.pem, http-path
    Note over OS: build a new EEPROM image:<br/>BOOT_ORDER (HTTP boot) + WALT_VPN_* variables<br/>(ssh and http entrypoints, boot mode, vpn mac, creds)
    OS->>BOARD: flash the EEPROM
    BOARD->>BOARD: reboot
    Note over BOARD: the node is now a VPN-capable node,<br/>next boot uses HTTP boot (see section 4)
```

The SSH entrypoint and the HTTP entrypoint are both written to the EEPROM, as
two distinct host names — they may be the same machine or different machines.

---

## 4. VPN boot of an RPi5 (subsequent boots)

Once enrolled, at every boot the RPi5 *HTTP-boots* `boot.img` + `boot.sig`,
and then opens an SSH tunnel through the SSH entrypoint so that the regular
WalT network boot (NFS root) can continue over the walt-net. The HTTP and SSH
entrypoints may be the same or different machines, as shown below.

```mermaid
sequenceDiagram
    autonumber
    participant R as "RPi5 firmware"
    participant EPHTTP as "HTTP entrypoint<br/>(may be a different machine<br/>from the SSH entrypoint)"
    participant EPSSH as "SSH entrypoint<br/>(may be a different machine<br/>from the HTTP entrypoint)"
    participant S as "WALT server<br/>(daemon + httpd, on walt-net)"
    participant IM as "initramfs<br/>(from boot.img)"

    R->>R: power on, follow EEPROM boot order<br/>(HTTP boot enabled)
    R->>EPHTTP: firmware HTTP boot: GET boot.img + boot.sig
    EPHTTP->>S: (routes the request into walt-net)
    S-->>EPHTTP: boot.img + boot.sig
    EPHTTP-->>R: boot.img + boot.sig
    R->>R: verify boot.sig with EEPROM public.pem<br/>load kernel + initramfs from the FAT boot.img
    R->>IM: hand over to kernel + initramfs
    IM->>IM: read EEPROM creds, set up a TAP interface
    IM->>EPSSH: SSH tunnel into walt-net<br/>(auth: node SSH certificate,<br/>verify: entrypoint host keys)
    EPSSH->>S: (SSH tunnel endpoint)
    Note over IM,S: the node is bridged into the walt-net<br/>through the SSH tunnel
    IM->>S: WalT network boot continues:<br/>mount NFS root over the tunnel
    S-->>IM: root filesystem
    IM->>IM: /bin/walt-init (normal WalT boot)
    Note over IM: the node now runs the WalT OS image
```

---

## 5. VPN boot mode versus board boot order

These two notions are related but distinct:

- **VPN boot mode** (`enforced` / `permissive`) is a **WALT-specific notion**,
  a per-node setting managed on the WalT server.
- **Boot order** is a **standard Raspberry Pi firmware setting**, stored in the
  EEPROM, that lists the boot methods the firmware is allowed to try (SD card,
  TFTP, HTTP boot, ...).

They are connected through the EEPROM programming: when an RPi5 enrolls or when
its VPN settings change, the node (via the auto-enroll service) translates the
WALT *VPN boot mode* into a standard firmware *boot order* and flashes it.

```mermaid
flowchart LR
    subgraph MODE["WALT 'VPN boot mode' (WALT-specific concept)"]
        E["enforced"]
        P["permissive"]
    end
    subgraph BOOT["Board 'boot order' (standard Raspberry Pi firmware<br/>setting, stored in the EEPROM: BOOT_ORDER = list of<br/>allowed boot methods: HTTP boot / TFTP / SD card / ...)"]
        O["BOOT_ORDER value"]
    end
    E -->|"signed HTTP boot only<br/>(0xf7)"| O
    P -->|"HTTP boot, then TFTP,<br/>then SD card (0xf127)"| O
```

When do these settings get (re)flashed?

- At **enrollment** (section 3): a first EEPROM image is written.
- Later, when the **VPN settings change on the server** (entrypoints, boot
  mode), on the next classical boot of the node the auto-enroll service
  compares the server's `node-conf` with the current EEPROM values and, if they
  differ, flashes a new EEPROM image to apply the new entrypoints / boot mode.
- The firmware then uses the boot order at each power-on.

---

## 6. What the OS image must provide

A nontrivial part of the boot procedure lives **inside the OS image**: the
initramfs is part of the image, and so are the boot files and the enrollment
service. This means the OS image is not a passive payload — it must be built
with RPi5 VPN support.

The default WalT OS images for RPi5 nodes (`rpi64-debian`) are built from the
`walt-images` repository (Dockerfile `base/rpi64/debian/Dockerfile`, overlay
`overlays/rpi64-debian`). Concretely, the image contributes:

- **A systemd service** `walt-vpn-auto-enroll.service`
  (`overlays/rpi64-debian/etc/systemd/system/...`, script
  `usr/bin/walt-vpn-auto-enroll`). Started once the OS is booted, it performs
  enrollment (section 3) and re-flashes the EEPROM when VPN settings change
  (section 5). It runs only on real hardware, not in `walt image shell`.
- **`/boot/update-boot-files.sh`** (`overlays/rpi64-debian/boot/...`), which
  builds the `boot.img` FAT archive for HTTP boot from the RPi boot files, and
  keeps it up to date:
  - at image build time, to produce the shipped image;
  - automatically, so that when a WALT user modifies a running OS image (e.g.
    with `walt image shell <image>` then `apt upgrade` to change the kernel or
    initramfs, or edits boot files in `<image>:/boot/rpi-5-b/`), `boot.img` is
    regenerated to reflect those changes without the user needing to know about
    the mechanism. When such an updated image is later mounted, the server
    (re)signs it (section 2).
- **Boot files** under `<image>:/boot/rpi-5-b/` (kernel, initramfs, firmware
  config, `cmdline`...), gathered into `boot.img`.

### Third-party images may not support RPi5 VPN boot

Because an important part of the mechanism lives inside the OS image, some
third-party WALT images may **not** support RPi5 VPN booting. Such an image can
usually still be booted **only from the walt-net** (classical TFTP boot); it
just cannot provide the HTTP boot / enrollment / tunnel pieces described above.

---
