
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

Note: an interactive configuration interface will be displayed first.
For more information about WalT network concepts and configuration, see [`walt help show networking`](networking.md).


## 5- Configuring docker hub credentials

In order to be able to use `walt` command line tool, you need valid docker hub credentials.
If you do not have such an account yet, register at https://hub.docker.com/signup.
Then, start `walt` tool and answer questions:
```
$ walt
Starting configuration procedure...
ip or hostname of WalT server: localhost
Docker hub credentials are missing, incomplete or invalid.
(Please get an account at hub.docker.com if not done yet.)
username: <docker-hub-user>
password: <docker-hub-password>

Configuration was stored in /root/.walt/config.

Resuming normal operations...
[...]
```

## 6- Start playing!

The system is now all set.
You can first verify that the system is running well by creating a virtual node.
```
$ walt node create vnode1
$ walt node shell vnode1
```

After a few minutes (download of the default image + node bootup) you should be connected on the virtual node.

Then, connect physical nodes and check that you can reach them (see [`walt help show node-install`](node-install.md)).
Caution: do not connect a node directly to the server (with no intermediate switch). It will NOT work.
(See [`walt help show networking`](networking.md) and [`walt help show switch-install`](switch-install.md).)

