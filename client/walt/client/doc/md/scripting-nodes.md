# scripting API: node management

Scripting features for node management are available at `walt.client.api.nodes`:

```
(.venv) ~/experiment$ python3
>>> from walt.client import api
>>> api.nodes
< -- API submodule for WALT nodes --

  methods:
  - self.create_vnode(self, node_name): Create a virtual node
  - self.get_nodes(self, node_set='all-nodes'): Return nodes of the platform
>
>>>
```

## Creating a virtual node

```
>>> from walt.client import api
>>> vn23 = api.nodes.create_vnode('vn23')
Node vn23 is now booting your image "pc-image:latest".
Use `walt node boot vn23 <other-image>` if needed.
>>> vn23
< -- virtual node vn23 --

  read-only attributes:
  - self.booted: False
  - self.config: <node configuration>
  - self.device_type: 'node'
  - self.gateway: ''
  - self.image: <image pc-image>
  - self.ip: '192.168.152.6'
  - self.mac: '52:54:00:2b:d4:76'
  - self.model: 'pc-x86-64'
  - self.name: 'vn23'
  - self.netmask: '255.255.255.0'
  - self.owner: 'eduble'  # yourself
  - self.type: 'node'
  - self.virtual: True

  methods:
  - self.boot(self, image, force=False): Boot the specified WalT image
  - self.get_logs(self, realtime=False, history=None, timeout=-1): Iterate over historical or realtime logs
  - self.reboot(self, force=False, hard_only=False): Reboot this node
  - self.remove(self, force=False): Remove this virtual node
  - self.rename(self, new_name, force=False): Rename this virtual node
  - self.wait(self, timeout=-1): Wait until node is booted
>
>>>
```

## Getting access to plaform nodes

Use api method `api.nodes.get_nodes()`:
```
>>> nodes = api.nodes.get_nodes()   # default is to get all nodes
>>> len(nodes)
9
>>> nodes = api.nodes.get_nodes('my-nodes')
>>> len(nodes)
6
>>> nodes = api.nodes.get_nodes('rpibp,vn23')
>>> len(nodes)
2
>>> nodes = api.nodes.get_nodes(['rpibp', 'vn23'])
>>> len(nodes)
2
>>> nodes
< -- Set of WalT nodes (2 items) --

  methods:
  - self.boot(self, image, force=False): Boot the specified image on all nodes of this set
  - self.filter(self, **kwargs): Return the subset of nodes matching the given attributes
  - self.get(self, k, default=None): Return item specified or default value if missing
  - self.get_logs(self, realtime=False, history=None, timeout=-1): Iterate over historical or realtime logs
  - self.items(self): Iterate over key & value pairs this set contains
  - self.keys(self): Iterate over keys this set contains
  - self.reboot(self, force=False, hard_only=False): Reboot all nodes of this set
  - self.values(self): Iterate over values this set contains
  - self.wait(self, timeout=-1): Wait until all nodes of this set are booted

  sub-items:
  - self['rpibp']: <node rpibp>
  - self['vn23']: <virtual node vn23>

  note: these sub-items are also accessible using self.<shortcut> for handy completion.
        (use <obj>.<tab><tab> to list these shortcuts)
>
>>>
```

## Working with node sets

Some API functions such as `api.nodes.get_nodes()` return a set of nodes.
Sets of nodes provide the following features:
* nodes in the set can be accessed by using their name (e.g. `nodes['rpibp']`);
* they provide group operations for all nodes of the set, such as `reboot()`, `wait()`, `get_logs()` functions;
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

## Interacting with a given node

Interacting with a given node is pretty obvious, as shown in this interactive session:

```
>>> rpibp = nodes['rpibp']
>>> rpibp
< -- node rpibp --

  read-only attributes:
  - self.booted: True
  - self.config: <node configuration>
  - self.device_type: 'node'
  - self.gateway: ''
  - self.image: <default for rpi-b-plus nodes>
  - self.ip: '192.168.152.3'
  - self.mac: 'b8:27:eb:68:a2:df'
  - self.model: 'rpi-b-plus'
  - self.name: 'rpibp'
  - self.netmask: '255.255.255.0'
  - self.owner: 'waltplatform'  # node is free
  - self.type: 'node'
  - self.virtual: False

  methods:
  - self.boot(self, image, force=False): Boot the specified WalT image
  - self.forget(self, force=False): Forget this node
  - self.get_logs(self, realtime=False, history=None, timeout=-1): Iterate over historical or realtime logs
  - self.reboot(self, force=False, hard_only=False): Reboot this node
  - self.rename(self, new_name, force=False): Rename this node
  - self.wait(self, timeout=-1): Wait until node is booted
>
>>> rpibp.reboot()
Node rpibp: rebooted ok.
>>> 
```

These operations can be automated in a script, for instance to emulate `walt node reboot <node-name>`:

```
import sys
from walt.client import api

if len(sys.argv) < 2:
    sys.exit('Node name is missing.')
nodes = api.nodes.get_nodes()
node_name = sys.argv[1]
if node_name not in nodes:
    sys.exit(f'Could not find node {node_name} on the platform!')
node = nodes[node_name]
node.reboot()
```


## Booting a WalT image

Method `<node>.boot()` allows to boot a WalT image on a single node:

```
>>> vn23.boot('pc-x86-64-test-suite')
Node vn23 will now boot pc-x86-64-test-suite.
Node vn23: rebooted ok.
>>>
```

Instead of specifying the image by its name, one can also specify an image object:

```
>>> images = api.images.get_images()
>>> test_suite_image = images['pc-x86-64-test-suite']
>>> vn23.boot(test_suite_image)
Node vn23 will now boot pc-x86-64-test-suite.
Node vn23: rebooted ok.
>>>
```

See [`walt help show scripting-images`](scripting-images.md) for more info about image objects.

Alternatively, method `<set-of-nodes>.boot()` can also be used to boot an image on several nodes at once.


## Working with logs

Method `<node>.get_logs()` is the same as `api.logs.get_logs()` with the
parameter `issuers` set to `<node>`. See [`walt help show scripting-logs`](scripting-logs.md) for more info.
