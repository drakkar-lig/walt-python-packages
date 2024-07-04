
# WalT server upgrade

This section explains how to upgrade a WalT server.
When a new version of WalT is available, you can follow these steps to update it.


## Preliminary check

This procedure works for upgrading your debian-based WalT server installation,
considering your OS is at least Debian Bullseye (Debian 11).
You can verify it using:
```
$ grep VERSION /etc/os-release
```

For upgrading an older installation, contact us at `walt-contact at univ-grenoble-alpes.fr`.


## Upgrade procedure

```
$ apt update; apt install -y python3-venv debian-archive-keyring
$ python3 -m venv /opt/walt-9.0
$ /opt/walt-9.0/bin/pip install --upgrade pip
$ /opt/walt-9.0/bin/pip install walt-server walt-client
$ /opt/walt-9.0/bin/walt-server-setup
```

Your server is now upgraded to current version.
