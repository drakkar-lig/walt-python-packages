
Welcome to WalT integrated help.

# Admin documentation

For installation and upgrade procedures (server, network switches, nodes, VPN) and a general view of WalT network structure, checkout [`walt help show admin`](admin.md).

# User documentation

## Getting started

In order to get familiar with main WalT concepts, see [`walt help show tutorial`](tutorial.md).

## General concepts

### Node-related terminology

To understand why a given user owns a given node or not, and for related aspects of terminology, see [`walt help show node-terminology`](node-terminology.md).

### Working with nodes and images

WalT provides:
* direct access to nodes (using `walt node shell`, `walt node cp` for instance)
* access to the underlying operating system image (using `walt image shell`, `walt image cp`, etc.)

For details, see:
* [`walt help show shells`](shells.md)
* [`walt help show node-cp`](node-cp.md)
* [`walt help show image-cp`](image-cp.md)

### Log management

WalT provides a logging system to manage your experiment logs.
See [`walt help show logging`](logging.md) for more info.

## Advanced users

For specific needs, it is possible to build your own WalT image from scratch.
See [`walt help show image-from-scratch`](image-from-scratch.md) for more info.

And if you want to connect a new kind of node which WalT does not currently
supports, check-out [`walt help show new-node-support`](new-node-support.md).

## How it works

See [`walt help show node-bootup`](node-bootup.md) for detailed understanding
of walt core.
