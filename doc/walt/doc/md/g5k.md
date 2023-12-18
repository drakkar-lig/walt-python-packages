# Deploying WalT on Grid'5000

[Grid-5000](https://www.grid5000.fr), sometimes abbreviated G5K, is a large-scale academic
testbed made of server-class nodes and spanning over 8 cities in France.

By installing the walt-client package with its `g5k` plugin on one of the G5K front-end
machines, users can easily deploy a WalT platform over one or several Grid-5000 sites.

A terminal screen record showing usage of WalT on Grid'5000 is available at:
https://asciinema.org/a/414589


## How it works

The `walt g5k deploy` command first reserves G5K nodes and a virtual LAN (VLAN) according to
the criteria specified by the user.
The reserved VLAN will be used as the WalT platform network.
One of the G5K nodes equipped with 2 or more ethernet interfaces is setup as a WalT server.
Its first network interface remains in the default VLAN for proper communication with the
`walt` client tool. The secondary interface is attached to the WalT network VLAN.
All other G5K nodes become WalT nodes. Their first network interface is attached to the
WalT network VLAN.


## Benefits

This WalT-on-G5K feature allows:
- to experiment WalT usage without having to install a WalT platform;
- to run WalT experiments on a large number of nodes.


## Limits

You must have a Grid'5000 account to be able to use this feature.
Compared to the remote access provided by such a public platform, a WalT platform
installed locally is more flexible and eases low level debugging steps since users
have physical access to nodes and network equipment.
Since the G5K platform is open to many users, one must also follow resource reservation
and usage restrictions (https://www.grid5000.fr/w/Grid5000:UsagePolicy).
The plugin currently only manages x86 G5K nodes, thus WalT-on-G5K users are restricted
to this node architecture.
WalT-on-G5K relies on some rarely used G5K features, thus deployment failures are not
so rare. Most notably, multi-site deployments rely on the establishment of a virtual LAN
spanning over the G5K sites, which involves dynamic configuration of G5K network switches,
a G5K feature which fails from time to time.


## Setup

Connect to one of the G5K front-ends, and install the walt-client package with its
`g5k` plugin:

```
$ ssh grenoble.g5k
[...]
eduble@fgrenoble:~$ pip3 install walt-client[g5k]
[...]
eduble@fgrenoble:~$
```

This will install the software in `$HOME/.local`.
If not done yet, you should update your `PATH` variable accordingly:

```
eduble@fgrenoble:~$ echo 'PATH=$PATH:$HOME/.local/bin' >> .bash_profile
eduble@fgrenoble:~$ source .bash_profile
```

You are now ready to use WalT with the G5K plugin:

```
eduble@fgrenoble:~$ walt
```

Optionally, you can also set up bash autocompletion for the `walt` tool:

```
eduble@fgrenoble:~$ mkdir -p $HOME/.local/share/bash-completion/completions
eduble@fgrenoble:~$ walt advanced dump-bash-autocomplete > \
                    $HOME/.local/share/bash-completion/completions/walt
```

Then you have to log out and log in again to reload these completion settings.


## Usage

The G5K plugin adds a set of sub-commands to `walt` grouped in the `g5k` category.
You can type `walt g5k` to list them.

The main sub-command is `walt g5k deploy`. When run without an argument, it starts
an interactive command-line interface for specifying WalT platform deployment
parameters: in which G5K sites should the WalT server and nodes be reserved, what
should be the duration of the reservation, etc. Then the deployment starts.

The sub-command `walt g5k wait` is useful to follow the deployment steps. It returns
when the WalT platform is ready. Deployments usually take approximately 10min.

Once the WalT platform is ready, you can start to use the other sub-command categories
(e.g. `walt image show`, `walt node show`, `walt node shell`, etc.) as you would with
any regular WalT platform.

In order to ease restarting the same deployment, the user has the possibility to save
the selected deployment parameters by giving a name to a deployment "recipe".
Such a saved recipe can be re-deployed by using `walt g5k deploy <recipe-name>`.

The sub-command `walt g5k info` allows to display the status of the current or last
deployment.
The sub-command `walt g5k release` allows to discard the current WalT deployment
and associated resources before the end of the G5K reservation.

The other sub-commands provide basic management of deployment recipes.
