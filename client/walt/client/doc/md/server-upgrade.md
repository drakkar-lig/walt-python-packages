
# Server upgrade procedures

This section explains how to upgrade a WalT server.

We consider that the server was first installed with our provided installation image (see [`walt help show server-install`](server-install.md)).
When a new version of WalT server software is available, you can follow these steps to update it.


# Upgrading from version 4 (may 2019)

This is a major upgrade. Main changes that affect this procedure are:
1. OS version was updated (debian **stretch** to debian **buster**)
2. WalT software now uses `python3` instead of `python2`
3. WalT server now uses `buildah`, `podman`, `skopeo` instead of `docker` for image management

Let's start.
First, we must stop and disable walt server daemon.
```
$ systemctl stop walt-server
$ systemctl disable walt-server
```

It is recommended to save the database, just in case the database version upgrade would fail.
```
$ pg_dump -Fc walt > walt-db.dump
```

Then we can remove obsolete python2 version of walt components and obsolete docker version:
```
$ python -m pip uninstall walt-server walt-virtual walt-client walt-common
$ apt remove docker-engine
```

Then, we must update the software repositories configuration:
```
$ sed -i -e 's/stretch/buster/g' /etc/apt/sources.list
$ DOCKER_REPO=https://download.docker.com/linux/debian
$ curl -fsSL $DOCKER_REPO/gpg | apt-key add -
$ KUBIC_REPO=https://download.opensuse.org/repositories/devel:kubic:libcontainers:stable/Debian_10
$ curl -fsSL $KUBIC_REPO/Release.key | apt-key add -
$ echo "deb [arch=amd64] $DOCKER_REPO buster stable" > /etc/apt/sources.list.d/docker.list
$ echo "deb $KUBIC_REPO/ /" > /etc/apt/sources.list.d/devel:kubic:libcontainers:stable.list
```

And we can start the OS upgrade:
```
$ apt update
$ apt dist-upgrade
```

When asked:
- you should answer "yes" when asked about upgrading libc
- you should answer "yes" when asked about automatically restarting services
- you can ignore the message about postgresql-common pakage (we will do the database upgrade below)
- you must keep local version of configuration files.
- you can safely reinstall the new version of grub on the disk boot sector (usually /dev/sda)

Next, we must install missing or up-to-date components:
```
$ apt install buildah podman skopeo docker-ce docker-ce-cli containerd.io python3-dev
$ curl -s https://bootstrap.pypa.io/get-pip.py -o get-pip.py && python3 get-pip.py
```

During OS upgrade postgresql package was updated from version 9.6 to 11. We must now upgrade WalT database accordingly:
```
$ pg_dropcluster --stop 11 main   # remove default cluster created during package upgrade
$ pg_upgradecluster 9.6 main
$ pg_dropcluster 9.6 main
```

Finally, we can install our new version of walt:
```
$ pip3 install --upgrade walt-server walt-client
```

Now, we must reboot the server. Note: this is mandatory (otherwise walt server will fail to
mount images).
```
$ reboot
```

Now we can start the upgraded walt service.
Note that on this first start, WalT service will have to copy docker images to its own repository now managed by `podman`.
This can take a long time. For a clear view, we recommend to first start it manually:
```
$ walt-server-daemon    # manual start
```

When image migration steps are done, you can stop the process using ctrl-C.
Then you can restart it as a systemd service:
```
$ systemctl start walt-server
$ systemctl enable walt-server
```

Your server is now upgraded to current version.


# Upgrading from version 5 (september 2020)

An apt registry key has changed:

```
$ KUBIC_REPO=https://download.opensuse.org/repositories/devel:kubic:libcontainers:stable/Debian_10
$ curl -fsSL $KUBIC_REPO/Release.key | apt-key add -
```

WALT now uses an additional tool called `skopeo`:

```
$ apt update
$ apt install skopeo
```

We can now upgrade walt software itself. This depends whether you are using the development mode
or the production mode.
If directory `/root/walt-python-packages` directory exists on your server, you are in
development mode, otherwise in production mode.

Production mode:
```
$ pip3 install --upgrade walt-server walt-client
```

Development mode:
```
$ cd /root/walt-python-packages
$ git checkout dev
$ git pull
$ make install
```

Then you can restart walt service:
```
$ systemctl restart walt-server
```

Your server is now upgraded to current version.
