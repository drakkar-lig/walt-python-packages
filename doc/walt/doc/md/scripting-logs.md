# scripting API: logs management

Scripting features for logs management are available at `walt.client.api.logs`:

```
(.venv) ~/experiment$ python3
>>> from walt.client import api
>>> api.logs
< -- API submodule for WALT logs --

  methods:
  - self.get_logs(self, realtime=False, history=None, issuers='my-nodes', timeout=-1): Iterate over historical or realtime logs
>
>>>
```

Currently, only one method is available: `api.logs.get_logs()`.
It allows to retrieve log lines in realtime and/or from the past.
See [`walt help show logging`](logging.md) for information about WalT logging system.

Since this command may match a large number of log lines, it actually returns an iterable object.
You can then use a for loop (see next examples) to iterate over it and break the loop when relevant.
If you are sure the number of log lines is not too high, you can also use `list(api.nodes.get_logs(...))` to get a list.


## Retrieving logs in realtime

Here is a first example:

```
>>> for logline in api.logs.get_logs(realtime=True):
...     if logline.stream == 'api-example':
...         print(logline)
... 
Log(timestamp=datetime.datetime(2023, 4, 21, 11, 28, 32, 317186), line='log line sent from node vn23', issuer=<virtual node vn23>, stream='api-example')
Log(timestamp=datetime.datetime(2023, 4, 21, 11, 30, 30, 746634), line='another log line sent from node vn23', issuer=<virtual node vn23>, stream='api-example')
```

Note that the log lines displayed above were generated from the following parallel terminal session:

```
(.venv) ~/experiment$ walt node shell vn23
Caution: changes outside /persist will be lost on next node reboot.
Run 'walt help show shells' for more info.
[...]
root@vn23:~# walt-log-echo api-example 'log line sent from node vn23'
root@vn23:~# walt-log-echo api-example 'another log line sent from node vn23'
root@vn23:~#
```

It is possible to specify a timeout value in seconds:

```
>>> from walt.client.exceptions import TimeoutException
>>> try:
...     for logline in api.logs.get_logs(realtime=True, timeout=5):
...         if logline.issuer.name == 'vn23':
...             print('got a log line from vn23')
...             break
... except TimeoutException:
...     print('vn23 was silent!')
...
vn23 was silent!
>>>
```

## Retrieving logs from the past

Here is a command retrieving logs issued in the last 10 minutes:

```
>>> for logline in api.logs.get_logs(history='-10m:'):
...     if logline.stream == 'api-example':
...         print(logline)
...
Log(timestamp=datetime.datetime(2023, 4, 21, 11, 28, 32, 317186), line='log line sent from node vn23', issuer=<virtual node vn23>, stream='api-example')
Log(timestamp=datetime.datetime(2023, 4, 21, 11, 30, 30, 746634), line='another log line sent from node vn23', issuer=<virtual node vn23>, stream='api-example')
>>>
```

Checkout [`walt help show log-history`](log-history.md) for information about the expected format for the `history` parameter.


## Combining realtime and recent history

In some cases, it is useful to enable both `realtime` and `history` options:

```
>>> vn23.reboot()
Node vn23: rebooted ok.
>>>
>>> for logline in api.logs.get_logs(history='-2m:', realtime=True, issuers='server'):
...     if 'booted' in logline.line:
...         print(logline)
...         break
...
Log(timestamp=datetime.datetime(2023, 4, 21, 11, 47, 15, 55869), line='node vn23 is booted', issuer=<walt server>, stream='platform.nodes')
>>>
```

In this example, `get_logs()` retrieves any logs issued by the WalT server during the past two minutes, and then continue retrieving new logs in realtime (unless the break was reached, of course).


## Specifying and analysing issuers

By default, only log lines issued by the nodes of the calling user are retrieved.
Option `issuers` can be used to change this default filter.

Various forms are allowed for the value of this option, such as:
- `issuers='my-nodes'`      # same as default value
- `issuers='server'`        # see example of previous section
- `issuers='all-nodes'`     # also include free nodes and nodes of other users
- `issuers='my-nodes,server'`
- `issuers=('vn23',)`
- `issuers=('vn23', 'rpibp')`

It is also possible to use an API object representing a set of nodes, for instance:

```
>>> nodes = api.nodes.get_nodes()
>>> nodes = nodes.filter(model='pc-x86-64')
>>> loglines = list(api.logs.get_logs(history='-30m:', issuers=nodes))
```

As shown in the examples of previous sections, each log line has an attribute called `issuer` which indicates the machine which issued it.
The value of this attribute is an API object. It may be either:
- a node object -- see [`walt help show scripting-nodes`](scripting-nodes.md) for more info about node objects
- a server object -- see [`walt help show scripting-tools`](scripting-tools.md)

If needed, one can easily differentiate these two kinds of issuers by checking the `device_type` attribute they both have.
