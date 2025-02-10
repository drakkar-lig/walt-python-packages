# WalT client software installation

Most users use ssh to connect to the WalT server and use the walt client already
installed there.

However, it is possible to install this client software on another machine, as
described below.
Known compatible operating systems include GNU/Linux, Mac OS, and Windows.
Please use Windows Subsystem for Linux (WSL) in the latter case.

The installation is straightforward and must be done in a virtual environment:

```
~$ mkdir experiment
~$ cd experiment
~/experiment$ python3 -m venv .venv
~/experiment$ source .venv/bin/activate
(.venv) ~/experiment$ pip install --upgrade pip
(.venv) ~/experiment$ pip install walt-client
```

Checkout https://docs.python.org/3/library/venv.html for more information
about virtual environments.

You may also want to setup bash or zsh completion for the `walt` command on
this machine. See [`walt help show shell-completion`](shell-completion.md).
