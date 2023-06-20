# scripting API: miscellaneous tools

`walt.client.api.tools` lists miscellaneous methods not available in other modules.

```
(.venv) ~/experiment$ python3
>>> from walt.client import api
>>> api.tools
< -- Misc API features --

  methods:
  - self.get_server(self): Return an API object describing the server
>
>>>
```

For now, one method is listed only: `get_server()`.
It obviously allows to get basic data about the walt server.

```
>>> api.tools.get_server()
< -- walt server --

  read-only attributes:
  - self.device_type: 'server'
  - self.ip: '192.168.152.1'
  - self.mac: '52:54:00:54:5c:93'
  - self.walt_version: '8'
>
>>>
```
