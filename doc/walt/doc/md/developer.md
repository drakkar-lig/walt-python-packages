
# Developer documentation summary

This section explains various topics helpful to participate with the software
development of WALT.


## Collaborative workflow

If you want to participate in the development of walt, email us:
walt-contact at univ-grenoble-alpes.fr

We welcome any contribution, bugfix, new feature, documentation update, more
automated tests, etc.
If you implement something, you can use the "pull request" feature of github.
WalT is based on various github repositories. Scroll down for the list.


## Experimental setup

Each developer must install a dedicated WALT platform for allowing development
and testing without disturbing experimental work or other developers.
This involves:

1. Install walt server software on a dedicated machine.
2. Optionally, connect one or more network switches, and physical nodes
   (or just use virtual nodes).

Note about step 1: since the purpose of this platform is just software development,
a small-form-factor PC is largely enough. But remember that walt server software
starts various network daemons, so the machine should be dedicated for this purpose
only. Don't try to install walt server software on your laptop!

With this setup in place, the developer can connect as root to the development server,
and modify the code, restart the main server daemon, test walt client tool, etc.

For installing the server, you can mostly follow [`walt help show server-install`](server-install.md).
However, for a more developer-friendly setup, commands at step 2 should be replaced.

If you are a core developer (with push access to the repository) just run the
following instead:
```
root@walt-server$ git clone git@github.com:drakkar-lig/walt-python-packages.git
root@walt-server$ make -j install
```

If you are not a core developer, you can instead fork our repository by pointing your
browser to the following URL, and validate:
https://github.com/drakkar-lig/walt-python-packages/fork.
Then, run the two commands above, but clone you own repository instead (i.e., replace
`drakkar-lig` by your own username on github).

When you want to reinstall the code you modified, run `make -j install` again.


## Repositories

The WalT project relies on various code repositories:

* https://github.com/drakkar-lig/walt-python-packages: the main repository of WalT
  platform code. It includes server code, client code, common code, optional code
  to be installed on WalT OS images, etc. The various `walt-*` pip packages published
  on PyPI are built from this repository. For helping developers understand the code
  structure and various important topics, this repository has its own documentation
  pages. See [`walt help show dev-walt-python-packages`](dev-walt-python-packages.md).
* https://github.com/drakkar-lig/walt-images: a repository building various WalT OS
  images to be booted by WalT nodes, including the default image of each WalT node
  model we support.
* https://github.com/drakkar-lig/walt-node-boot: a repository for building network
  bootloaders useful to turn a computer into a WalT node. Some node models, such as
  recent Raspberry Pi board and some x86 computers do not need such a specific
  bootloader because their firmware is already capable of network booting. This
  repository remains useful for turning other kinds of computers or SBCs into WalT
  nodes.
* https://github.com/drakkar-lig/walt-project: the repository where we announce new
  WalT versions. With each version we link some build artefacts of the other
  repositories. There is no source code there. Since WalT relies on several code
  repositories, it is probably easier for the end user to find all these artefacts
  at a single place.
* https://github.com/drakkar-lig/python-apt-binary: the repository for building and
  uploading the pip package https://pypi.org/project/python-apt-binary. It allows to
  interact with debian package manager `apt`, when running `walt-server-setup` to
  install or upgrade a WalT server.  The underlying code is developed by Debian
  developers and available as a Debian package called `python3-apt`, but it was not
  available on PyPI, thus not installable in a python virtual environment.
* https://github.com/drakkar-lig/walt-vpn-node: the repository allowing to turn a
  raspberry pi 3B/3B+ board into a WalT VPN node. It generates an SD card image file.
  See [`walt help show vpn`](vpn.md) for more info.
