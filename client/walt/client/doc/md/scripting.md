# Scripting WalT experiments

Python package `walt-client` includes the scripting features described here.
This section is voluntarily light because the API objects useful for scripting are self-descriptive.
Their `__repr__()` method gives a precise description of which attributes, methods or subitems these objects have.
For this reason, users should first experiment using an interactive python shell:
each time an API object is returned, it will self-describe itself on standard output.

The entry point of the scripting features is object `walt.client.api`.

## Introductory example

The following is a sample interactive session exploring some of these features.

```
root@clipperton:~# python3
>>> from walt.client import api
>>> api
< -- WALT API root --

  read-only attributes:
  - self.images: <API submodule for WALT images>
  - self.nodes: <API submodule for WALT nodes>
>
>>> api.nodes
< -- API submodule for WALT nodes --

  methods:
  - self.create_vnode(self, node_name): Create a virtual node
  - self.get_nodes(self): Return nodes of the platform
>
>>> nodes = api.nodes.get_nodes()
>>> nodes
< -- Set of WalT nodes (5 items) --

  methods:
  - self.boot(self, image, force=False): Boot the specified image on all nodes of this set
  - self.filter(self, **kwargs): Return the subset of nodes matching the given attributes
  - self.get(self, k, default=None): Return item specified or default value if missing
  - self.items(self): Iterate over key & value pairs this set contains
  - self.keys(self): Iterate over keys this set contains
  - self.reboot(self, force=False, hard_only=False): Reboot all nodes of this set
  - self.values(self): Iterate over values this set contains
  - self.wait(self, timeout_secs=-1): Wait until all nodes of this set are booted

  sub-items:
  - self['rpi2b']: <node rpi2b>
  - self['rpi3pb']: <node rpi3pb>
  - self['rpi4b']: <node rpi4b>
  - self['rpibp']: <node rpibp>
  - self['vn10']: <virtual node vn10>

  note: these sub-items are also accessible using self.<shortcut> for handy completion.
        (use <obj>.<tab><tab> to list these shortcuts)
>
>>> rpibp = nodes['rpibp']
>>> rpibp
< -- node rpibp --

  read-only attributes:
  - self.booted: False
  - self.config: <node configuration>
  - self.gateway: '192.168.152.1'
  - self.image: <image rpi-debian>
  - self.ip: '192.168.152.16'
  - self.mac: 'b8:27:eb:68:a2:df'
  - self.model: 'rpi-b-plus'
  - self.name: 'rpibp'
  - self.netmask: '255.255.255.0'
  - self.owner: 'eduble'  # yourself
  - self.type: 'node'
  - self.virtual: False

  methods:
  - self.boot(self, image, force=False): Boot the specified WalT image
  - self.forget(self, force=False): Forget this node
  - self.reboot(self, force=False, hard_only=False): Reboot this node
  - self.rename(self, new_name, force=False): Rename this node
  - self.wait(self, timeout_secs=-1): Wait until node is booted
>
>>>
>>> rpibp.config.mount_persist
False
>>> rpibp.config.mount_persist = True
Done. Reboot node(s) to see new settings in effect.
>>> rpibp.reboot()
Node rpibp: rebooted ok.
>>>
```

Obviously, the operations tested in this interactive session can be automated in a python script file.
It would contain for instance:

```
import sys
from walt.client import api

nodes = api.nodes.get_nodes()
if 'rpibp' not in nodes:
    sys.exit('Could not find node rpibp on the platform!')
rpibp = nodes['rpibp']
rpibp.config.mount_persist = True
rpibp.reboot()
```


## Read-only and writable attributes

Node configuration attributes are writable. Other API objects only have read-only attributes.


## Sub-items shortcuts and interactive completion

When running an interactive session, it can be handy to use autocompletion of object attributes using the `<TAB>` key.

However, the `<object>[<sub-item>]` notation breaks this autocompletion.
For instance typing `nodes['rpibp'].<TAB><TAB>` will fail to list the attributes of node `rpibp`.

For this reason, object sets (such as variable `nodes` in this example) also provide access to sub-items using point-based notation.
In our example, one can for example type `nodes.rpibp` instead of `nodes['rpibp']`, and in this case `<TAB>`-completion works.

If a sub-item name contains characters forbidden in an attribute, they will be replaced by underscores.


## Node (and image) sets

Some API functions return a set of nodes. This is the case of `api.nodes.get_nodes()` for instance.
Sets of nodes provide the following features:
* nodes in the set can be accessed by using their name (e.g. `nodes['rpibp']`);
* they provide group operations for all nodes of the set, such as a `reboot()` function;
* they provide a `filter()` method allowing to select nodes having given attribute values (e.g. `nodes.filter(virtual=True, booted=True)`), and returning a new set of nodes;
* they provide the self-description features of API objects.

Here is a sample code which reboots all virtual nodes:
```
from walt.client import api
nodes = api.nodes.get_nodes()
nodes = nodes.filter(booted = True, virtual = True)
nodes.reboot()
```

Indeed the user is free to use regular python sets instead, such as in this example:
```
from walt.client import api
nodes = api.nodes.get_nodes()
nodes = set(n for n in nodes if n.booted and n.virtual)
for node in nodes:
    node.reboot()
```

One can also group individual nodes into a set by using binary-or operators:
```
>>> from walt.client import api
>>> nodes = api.nodes.get_nodes()
>>> nodes = nodes['rpi2b'] | nodes['rpi3b-test'] | nodes['rpibp']
>>> nodes
< -- Set of WalT nodes (3 items) --

  methods:
  - self.boot(self, image, force=False): Boot the specified image on all nodes of this set
  - self.filter(self, **kwargs): Return the subset of nodes matching the given attributes
  - self.get(self, k, default=None): Return item specified or default value if missing
  - self.items(self): Iterate over key & value pairs this set contains
  - self.keys(self): Iterate over keys this set contains
  - self.reboot(self, force=False, hard_only=False): Reboot all nodes of this set
  - self.values(self): Iterate over values this set contains
  - self.wait(self, timeout_secs=-1): Wait until all nodes of this set are booted

  sub-items:
  - self['rpi2b']: <node rpi2b>
  - self['rpi3b-test']: <node rpi3b-test>
  - self['rpibp']: <node rpibp>

  note: these sub-items are also accessible using self.<shortcut> for handy completion.
        (use <obj>.<tab><tab> to list these shortcuts)
>
>>>
```

For consistency, image sets are the same kind of object as node sets, but less useful because there are no group operations implemented on image sets.

