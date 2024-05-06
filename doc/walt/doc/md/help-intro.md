
# Welcome to WalT documentation!

The [WalT project](https://walt-project.liglab.fr) allows to easily build and use your own WalT testbed.
Up to now, WalT testbeds have been used for research experiments, medium-sized (e.g., 100 nodes) industrial testing infrastructures, and mobile demo setups.

## Scope and design notes

WalT is designed as **a tool for teammates**.
If many users want to use WalT, then **each team should install its own private WalT platform**.
Much of the versatility and user-friendliness we advertise comes from this concept of private platform.
See [`walt help show design-notes`](design-notes.md) for more info.

## Main features

WalT mainly provides the following set of features:
* **Physical access** (see below) and/or **remote control** over nodes
* Compatibility with various kinds of nodes:
  - **Raspberry Pi** B/B+/2B/3B/3B+/4B/400 nodes
  - **PC nodes** booted from a USB dongle
  - **Virtual nodes**
  - Distant Raspberry Pi nodes using WALT ssh-based **VPN** (experimental feature)
* **Management of node OS images**
  - Clone or publish them from/to the docker hub (or a private registry)
  - Modify them easily (virtual shell sessions, 1-command file copies)
* Means to collect, store and query **experiment logs**

A WALT platform is cost-effective, easy to install, easy to use, lightweight, versatile and collaborative.

## Optional features

With compliant network switches, WalT also provides the following *optional* features:
* **Platform topology automated discovery**;
* **PoE** for simplified deployment, possible **hard-reboot** (power-cycling) of nodes and automatic **power saving**.

See [`walt help show optional-features`](optional-features.md) for more info.

## A key feature: giving users physical access to nodes

WalT platforms provide a high level of versatility: they give users physical access to nodes.
At [LIG](https://www.liglab.fr) for instance, our main WalT platform network is deployed over a VLAN of the building.
Users can plug or unplug walt nodes (or, sometimes, network switches) from the wall plugs depending on the experiments they plan.

Debugging low-level kernel modifications of a network protocol is obviously much easier when having physical access to two or more of these nodes; with such a setup, the user can easily move two WalT nodes right to her desktop.

Moreover, users often use the USB ports of WalT nodes to plug other equipment.
For instance it is easy to setup an IoT testbed by connecting IoT boards on USB ports of WalT nodes. In this case, the experiment runs on the IoT boards and WalT nodes are configured as a control interface for them. WalT nodes boot a WalT image containing tools to flash a firmware or reboot the IoT board, and possibly catch the logs coming for the USB-serial link and turn them into WalT logs.

# Quick Links

## Admin documentation

For installation and upgrade procedures (server, network switches, nodes, VPN), a general view of WalT network structure, etc., checkout [`walt help show admin`](admin.md).

Note: as an alternative to a physical platform installation, or to get a first insight of WalT, Grid'5000 users can also deploy WalT on-demand on the Grid'5000 testbed. See [`walt help show g5k`](g5k.md).

## User documentation

In order to get familiar with main WalT concepts, see [`walt help show tutorial`](tutorial.md).
To understand why a given user owns a given node or not, and for related aspects of terminology, see [`walt help show node-ownership`](node-ownership.md).

WalT provides:
* direct access to nodes (using `walt node shell`, `walt node cp` for instance)
* access to the underlying operating system image (using `walt image shell`, `walt image cp`, etc.)

For details, see:
* [`walt help show shells`](shells.md)
* [`walt help show node-cp`](node-cp.md)
* [`walt help show image-build`](image-build.md)
* [`walt help show image-cp`](image-cp.md)

WalT also provides a logging system to manage your experiment logs (see [`walt help show logging`](logging.md)), python scripting features (see [`walt help show scripting`](scripting.md)), and many other features.

## Advanced topics

For specific needs, it is possible to build your own WalT image from scratch.
See [`walt help show image-from-scratch`](image-from-scratch.md) for more info.

If you want to connect a new kind of node which WalT does not currently
supports, check-out [`walt help show new-node-support`](new-node-support.md).

See [`walt help show node-bootup`](node-bootup.md) for detailed understanding
of walt nodes' bootup precedure.

## Developer documentation

To participate in the software development of WALT, checkout [`walt help show developer`](developer.md),
the entry point of the developer documentation.
