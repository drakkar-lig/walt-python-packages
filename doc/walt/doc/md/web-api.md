# Using the web API

This section explains how to interact with the web API WalT provides.

It can be used to export WalT platform data to another system, such as Grafana
and its "Infinity" datasource plugin.

The web API is managed by the web-server component (see [`walt help show web-server`](web-server.md)) and is available
 at `http://<walt-server>/api`.
The entrypoints are described below.
they all expect a `GET` request and return a JSON object or
an HTTP error.


## Entrypoint [/api/v1/nodes](/api/v1/nodes)

This entrypoint allows to retrieve data about the nodes.
Example:

```console
# curl -s "http://localhost/api/v1/nodes" | jq
{
  "num_nodes": 15,
  "nodes": [
    {
      "name": "dummy",
      "model": "pc-x86-64",
      "virtual": true,
      "image": "eduble/pc-x86-64-default:latest",
      "booted": true,
      "ip": "192.168.222.5",
      "mac": "52:54:00:bb:1b:b9",
      "config": {
        "netsetup": 1,
        "expose": "none",
        [...]
      }
    },
    {
      "name": "nanopi",
      "model": "nanopi-r5c",
      "virtual": false,
      "image": "eduble/nanopi-r5c-default
      "booted": false,
      "ip": "192.168.222.24",
      "mac": "52:e8:a1:60:81:e6",
      "config": {
        "netsetup": 1,
        "expose": "80:8080",
        [...]
      }
    },
    [...]
  ]
}
```

First-level attributes of each node are always:
`name`, `model`, `virtual`, `image`, `booted`, `ip`, `mac`, and `config`.
However, the content of the `config` item vary depending on several factors.
For instance, if the node is virtual, it has several more config items allowing
to define disks, networks, number of cpus, and amount of ram.

One can further refine the query by specifying one or more of the first-level
attributes:
```console
# curl -s "http://localhost/api/v1/nodes?booted=true&model=pc-x86-64"
[...]
```

Any of the first-level attributes can be specified like this except `config`.


## Entrypoint [/api/v1/images](/api/v1/images)

This entrypoint allows to retrieve data about the OS images available
on the WalT server.
Example:

```console
# curl -s "http://localhost/api/v1/images" | jq
{
  "num_images": 119,
  "images": [
    {
      "fullname": "eduble/pc-x86-64-2:latest",
      "user": "eduble",
      "id": "807e871055267897be0a7e29090844e65e0181660cda4728f6f2eaddec49ce6d",
      "in_use": false,
      "created": "2024-03-12 14:52:47",
      "compatibility": [
        "pc-x86-64"
      ]
    },
    {
      "fullname": "waltplatform/rpi-debian:bookworm",
      "user": "waltplatform",
      "id": "1739447a661b739aa127af56117c9468c039f1d612125862cfa6d89ae4df3363",
      "in_use": false,
      "created": "2024-03-12 10:35:17",
      "compatibility": [
        "rpi-b",
        "rpi-b-plus",
        "rpi-2-b",
        "rpi-3-b",
        "rpi-3-b-plus",
        "rpi-4-b",
        "rpi-400",
        "qemu-arm-32",
        "qemu-arm-64"
      ]
    },
    [...]
  ]
}
```

One can further refine the query by specifying one or more of the attributes
`fullname`, `user`, `id` and `in_use`. For instance:

```console
# curl -s "http://localhost/api/v1/images?user=eduble&in_use=false"
[...]
```


## Entrypoint `/api/v1/logs`

This entrypoint allows to retrieve platform and experiment logs from
WalT server database.
Example:

```console
# curl -s "http://localhost/api/v1/logs?from=1727090181&to=1727101440" | jq
{
  "num_logs": 4324,
  "logs": [
    {
      "timestamp": 1727090181.324492,
      "line": "scanning images...",
      "issuer": "walt-server",
      "stream": "daemon.stdout"
    },
    {
      "timestamp": 1727090181.737941,
      "line": "found testeduble/pc-x86-64-default:latest -- [...]",
      "issuer": "walt-server",
      "stream": "daemon.stdout"
    },
    [...]
  ]
}
```

Query parameters `from` and `to` are mandatory.
Their value must be encoded as a number of seconds since the Unix Epoch (i.e.,
00:00:00 UTC on 1 January 1970).
Floating-point values are accepted too.

The unit of timestamps may be specified by using optional query parameter `ts_unit`.
Accepted values are `ts_unit=s` (for seconds, the default) and `ts_unit=ms` (for
milliseconds).
If `ts_unit=ms` is specified, then:
* `from` and `to` must correspond to a number of milliseconds since the Unix Epoch;
* the `timestamp` attribute of logs is returned as a number of milliseconds too.

One can further refine the query by looking up a specific `issuer` and/or `stream`.
For instance:
```console
# curl -s "http://localhost/api/v1/logs?from=1727090180&to=1727101440&stream=netconsole"
[...]
```
