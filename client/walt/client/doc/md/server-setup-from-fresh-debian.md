
# Walt server setup from a fresh Debian OS

## Overview

These are the steps you should follow (as root user) to install the walt server system on a machine freshly installed
with debian 11 (bullseye) operating system.

Note that walt server software interacts with various network daemons (lldpd, snmpd, dhcpd, ptpd, ntpd,
tftpd, nfsd), thus you should not run other software related to network management on this walt server
machine.


## 1- Install a first set of packages

```
$ apt update
$ apt install -y gcc python3-dev libsmi2-dev python3-apt gpg curl git make
```

## 2- Install python package manager

```
$ curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py && python3 get-pip.py
```

## 3- Install walt software

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

## 4- Run walt automated setup command

```
$ walt-server-setup
```

## 5- Network configuration and testing

At this point, you should return to server install procedure [`walt help show server-install`](server-install.md)
for the remaining configuration and testing.

