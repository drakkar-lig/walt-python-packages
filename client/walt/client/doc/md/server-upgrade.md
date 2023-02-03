
# WalT server upgrade

This section explains how to upgrade a WalT server.
When a new version of WalT is available, you can follow these steps to update it.


## Preliminary check

This procedure works for upgrading your debian-based WalT server installation,
considering your OS is at least Debian Buster (Debian 9).
You can verify it using:
```
$ grep VERSION /etc/os-release
```

For upgrading an older installation, contact us at `walt-contact at univ-grenoble-alpes.fr`.


## Upgrade procedure

The upgrade depends whether you are using the development mode
or the production mode.
If directory `/root/walt-python-packages` directory exists on your server, you are in
development mode, otherwise in production mode.

Production mode:
```
$ pip3 install --upgrade walt-server walt-client
$ walt-server-setup
```

Development mode:
```
$ cd /root/walt-python-packages
$ git checkout dev
$ git pull
$ make install
$ walt-server-setup
```

Your server is now upgraded to current version.
