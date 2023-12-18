# Scripting WalT experiments

Python package `walt-client` includes the scripting features described here.
Installing `walt-client` in a virtual environment is recommended:

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


## Scripting API entrypoint

The entry point of the scripting features is object `walt.client.api`.

```
(.venv) ~/experiment$ python3
>>> from walt.client import api
>>> api
< -- WALT API root --

  read-only attributes:
  - self.images: <API submodule for WALT images>
  - self.logs: <API submodule for WALT logs>
  - self.nodes: <API submodule for WALT nodes>
  - self.tools: <Misc API features>
>
>>>
```

## Scripting API submodules

As shown in the previous interactive session, the entrypoint provides access to several API submodules:
- management of images (cf. [`walt help show scripting-images`](scripting-images.md)),
- management of nodes (cf. [`walt help show scripting-nodes`](scripting-nodes.md)),
- management of logs (cf. [`walt help show scripting-logs`](scripting-logs.md)),
- and a few more features (cf. [`walt help show scripting-tools`](scripting-tools.md)).


## Interactive shell versus script file

API objects useful for scripting are self-descriptive.
Their `__repr__()` method gives a precise description of which attributes, methods or subitems these objects have.
For this reason, users can get familiar with API features by first using an interactive python shell:
each time an API object is returned, it will self-describe itself on standard output.

Here is a sample interactive session:

```
(.venv) ~/experiment$ python3
>>> from walt.client import api
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

For this reason, object sets (such as variable `nodes` in the example above) also provide access to sub-items using point-based notation.
In our example, one can for example type `nodes.rpibp` instead of `nodes['rpibp']`, and in this case `<TAB>`-completion works.

If a sub-item name contains characters forbidden in an attribute (such as a dash), they will be replaced by underscores.

