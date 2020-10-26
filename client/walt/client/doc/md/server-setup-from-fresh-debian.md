
# Walt server setup from a fresh Debian operating system

## Overview

These are the steps you should follow to install the walt server system on a machine freshly installed
with debian 10 (buster) operating system.

Note that walt server software interacts with various network daemons (lldpd, snmpd, dhcpd, ptpd, ntpd,
tftpd, nfsd), thus you should not run other software related to network management on this walt server
machine.


## 1- Install a first set of packages

```
$ grep non-free /etc/apt/sources.list || sed -i -e 's/main/main non-free/g' /etc/apt/sources.list
$ apt-get update
$ apt-get install --upgrade --no-install-recommends \
        apt-transport-https ca-certificates gnupg2 curl gnupg-agent \
        software-properties-common binfmt-support qemu-user-static \
        lldpd snmp snmpd openssh-server snmp-mibs-downloader iputils-ping \
        libsmi2-dev isc-dhcp-server nfs-kernel-server uuid-runtime postgresql \
        ntpdate ntp lockfile-progs ptpd tftpd-hpa ebtables qemu-kvm bridge-utils \
        screen ifupdown gcc python3-dev git make sudo
```

## 2- Define secondary package repositories

```
$ URL="https://download.docker.com/linux/debian"
$ curl -sSL $URL/gpg | sudo apt-key add -
$ echo "deb [arch=amd64] $URL buster stable" > /etc/apt/sources.list.d/docker.list
$ URL="https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/Debian_10"
$ curl -sSL $URL/Release.key | sudo apt-key add -
$ echo "deb $URL/ /" > /etc/apt/sources.list.d/libcontainers.list
```

## 3- Install a second set of packages

```
$ apt-get update
$ apt-get install --upgrade --no-install-recommends \
        docker-ce docker-ce-cli containerd.io podman buildah skopeo
```

## 4- Install python package manager

```
$ curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && python3 get-pip.py
```

## 5- Install walt software

Here you have two options:
- Install the last official version of walt (recommended)
- Install the development version of walt (with last features and quick access to source code,
  but less thoroughly tested)

If you want the official version:
```
$ pip3 install walt-server walt-client
```

If you want to setup the development version instead:
```
$ cd /root
$ git clone https://github.com/drakkar-lig/walt-python-packages
$ cd walt-python-packages
$ git checkout -b dev origin/dev
$ make install
```

## 6- Update dhcpd configuration

```
$ sed -i -e 's/INTERFACESv4=.*/INTERFACESv4="walt-net"/g' /etc/default/isc-dhcp-server
$ update-rc.d isc-dhcp-server disable 2 3 4 5
```

## 7- Update tftpd configuration

```
$ cat > /etc/default/tftpd-hpa << EOF
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/var/lib/walt"
TFTP_ADDRESS="0.0.0.0:69"
TFTP_OPTIONS="-v -v --secure --map-file /etc/tftpd/map"
EOF
$ mkdir /etc/tftpd
$ cat > /etc/tftpd/map << EOF
# these first lines ensures compatibility of legacy
# bootloader configurations.
r boot/rpi-.*\.uboot start.uboot
r boot/pc-x86-64.ipxe start.ipxe
# generic replacement pattern
r .* nodes/\i/tftp/\0
EOF
$
```

## 8- Update ptpd configuration

```
$ cat > /etc/default/ptpd << EOF
# Set to "yes" to actually start ptpd automatically
START_DAEMON=yes

# Add command line options for ptpd
PTPD_OPTS="-c /etc/ptpd.conf"
EOF
$ cat > /etc/ptpd.conf << EOF
ptpengine:interface=walt-net
ptpengine:preset=masteronly
global:cpuaffinity_cpucore=0
global:ignore_lock=Y
global:log_file=/var/log/ptpd.log
global:log_status=y
ptpengine:domain=42
ptpengine:ip_dscp=46
ptpengine:ip_mode=hybrid
ptpengine:log_delayreq_interval=3
ptpengine:log_sync_interval=3
ptpengine:log_announce_interval=3
EOF
$
```

## 9- Update lldpd configuration

```
$ echo 'DAEMON_ARGS="-x -c -s -e -D snmp"' > /etc/default/lldpd
```

## 10- Update snmpd configuration

```
$ sed -i -e 's/.*community.*localhost/rocommunity private localhost/' /etc/snmp/snmpd.conf
```

## 11- Run walt automated setup commands

```
$ walt-server-setup
$ walt-virtual-setup --type SERVER --init-system SYSTEMD
```

## 12- Create walt server spec file

```
$ mkdir -p /etc/walt
$ cat > /etc/walt/server.spec << EOF
{
    # optional features implemented
    # -----------------------------
    "features": [ "ptp" ]
}
EOF
$
```

## 13- Network configuration and testing

At this point, you should return to server install procedure [`walt help show server-install`](server-install.md)
for the remaining configuration and testing.

