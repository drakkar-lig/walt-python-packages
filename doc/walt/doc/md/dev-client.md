
# Repository: walt-python-packages; walt-client code.

This section explains various things helpful when modifying the walt client code.

As a reminder, this code is in subdirectory `client` of repository
`walt-python-packages`, the code must maintain a compatibility with python 3.9,
and there are constraints regarding package dependencies.
See [`walt help show dev-walt-python-packages`](dev-walt-python-packages.md) for more info.


## Performance constraint

The `walt` tool provides many short-lived sub-commands such as `walt node show`,
`walt image show`, etc. Unlike daemons continuously running on the server, this
python tool has to reload from scratch very often.
For making its usage pleasant, those short-lived commands should run fast enough
(target <0.1s, even on slow machines).

For instance, at the time of this writting, here is the time I get on my development
platform:
```
root@ibiza:~# time walt node show

You currently own the following nodes:
[...]

real  0m0,054s
user  0m0,025s
sys	  0m0,012s
root@ibiza:~#
```

The code of the tool, and of its dependencies (`walt-common` and `walt-doc`), contains
various optimizations to achieve this goal:
* Many python imports are delayed just before they are really needed.
* When running `walt <category> <subcommand> <args>`, only the module specific to
  `<category>` is loaded, not others.
* The Logo is only loaded if needed.
* Various more optimizations are written in `walt.client.speedup` and loaded at client
  startup. More on this below.

The module `walt.client.speedup` allows to register a faster exit procedure, it
implements two tricks to improve `plumbum` module loading performance, and an optional
trick to improve loading time when the virtual environment is stored on a slow
filesystem (such as NFS, on Grid'5000).
It is implemented in file `client/walt/client/speedup.py`.

The module `walt.client.speedup` embeds quite complex code, but if you suspect
issues with this file, you can easily check: just remove the line
`import walt.client.speedup` at the top of `client/walt/client/client.py`.
The client should run correctly without it too, but slower. On my system,
without the import statement, `walt node show` is +133% slower.


## Library plumbum.cli

For managing the Command Line Interface (CLI), the client code relies on a library
called `plumbum`, and more-specifically its submodule `plumbum.cli`.

It relies on introspection to avoid duplicating things:
* The prototype of a `main()` function leads to usage rules
* Docstrings help building help messages automatically
* etc.

See https://plumbum.readthedocs.io/en/latest/cli.html for more info.

By convention, if you want the `walt` command to return a non-zero exit status to
indicate that a command failed or got invalid arguments, return `False` from the
`main()` function. See the comment in `wrap.py` for more info.


## Code structure

The client code is usually simple, with the code of each `<category>` stored in a file
`client/walt/client/<category>.py`, except category `help` which is stored in a file
named `myhelp.py` (for avoiding a conflict with the `help` builtin).

Other files factorize more elaborate processing.


## Communication with the server

Apart from a few local-only subcommands (e.g., `walt help` category), almost
all subcommands need to communicate with the server.


### General notes

Note: the client *never* communicates directly with nodes. Commands interacting with
nodes actually pass through the server. For instance, `walt node shell` relies on an
ssh command from the server to the node, and this ssh command runs in a terminal
emulated on the server; but the terminal input & output are forwarded up to the
client to give the impression that the SSH session is local.

Since we want the client to be easily installable, the communication between the
server and the client is based on a simple, custom protocol. And since we consider
walt platforms are installed on private networks, the communication between the
client and the server is not encrypted, except for passing the Docker Hub password
from the client to the server when using `walt image publish`.

Two server endpoints are used by the client:
* TCP port 12345: for remote-procedure-call (RPC) type of communication
* TCP port 12347: for other, more stream-based purposes

These port numbers are defined in `common/walt/common/constants.py`.
More info below.


### RPC communication

RPC communication is abstracted using the following kind of fragment:
```
with ClientToServerLink() as server:
    server.create_vnode(node_name)
```

This example manages `walt node create <node_name>`, and can be found in
`client/walt/client/node.py`.

On server side, this code calls the function `CSAPI.create_vnode(context, node_name)`
which can be found in `server/walt/server/processes/main/api/cs.py`.
`CS` stands for `Client to Server`.


### Stream-based communication

Stream based communication works like in the following kind of fragment:
```
# connect to server
sock = connect_to_tcp_server()
# send the request id
Requests.send_id(sock, Requests.REQ_VPN_NODE_IMAGE)
# wait for the READY message from the server
sock.readline()
# custom processing on sock
[...]
# end
sock.close()
```

This code is the one behind `walt vpn setup-node`. It dumps a SD card image file
for turning a raspberry pi board into an autonomous walt VPN node.

Variable `sock` in a file object obtained from the plain socket object using
`socket.makefile()`, so it provides `sock.read(<bufsize>)` and `sock.write(<bin-data>)`
for easy communication with the server.

In this case, the custom processing is just about sending parameters for the server
to generate an appropriate image, and then a loop to read the SD card image that the
server streams over the socket, and write this image to a file.

The list of current request types (such as `REQ_VPN_NODE_IMAGE` here) can be seen
in `common/walt/common/tcp.py`. Note: some of them are used by the nodes, not by the
clients (e.g., `REQ_NEW_INCOMING_LOGS`, `REQ_FAKE_TFTP_GET`).

This kind of communication is also used for implementing remote shells, file transfers,
log retrieval.


## Information about complex code parts

Since we want to have a fast and easily installable client tool, complex things
are implemented on server side whenever possible.
Next sections describe a few client modules still presenting some level of complexity.


### Interactive shell commands

Interactive shell commands (e.g., `walt node shell`, `walt image shell`) are probably
the most complex part of the client code. They are mostly implemented in file
`interactive.py`. We decribe below how it works.

Terminal emulation is implemented on server side. The `walt` client tool sets its own
terminal in 'raw' mode, in order to avoid interpreting any escape sequence (ctrl-r,
etc.). As a consequence, these sequences are just forwarded over the socket connection
up to the terminal emulated on the server, and this remote terminal interprets them.

The `echo` feature (printing keys as they are typed) is also disabled on the local
terminal, otherwise keys would be echo-ed twice. It is better to consider that the
server terminal will handle all outputs, otherwise the synchronization between
the output coming from the client (echo) and from the server (command outputs, prompts)
would not be perfect because of network latency. Thus we let the server terminal
handle the echo.

The local terminal window size is also transmitted at startup, in order to let
the server emulate a terminal of the correct size. And the client monitors the
`SIGWINCH` signal to be able to transmit window size changes to the server.

File `console.py` is used for implementing `walt node console`, i.e. a shell
connected to the console of a virtual node. This file implements the same kind
of features, but the output data comes for the logging system instead of a
virtual terminal implemented on server side. This comes from the fact we capture
the console of virtual nodes as a suite of messages stored into the walt logging
system.


### Python scripting features

Python scripting features (see [`walt help show scripting`](scripting.md)) are implemented
at `client/walt/client/apitools.py` and in directory `client/walt/client/apiobject`.

The root `api` object (i.e., the object obtained by `from walt.client import api`) is
instanciated in file `client/walt/client/startup.py`.

Most of python scripting code reuses the code behind `walt` client tool subcommands.
However, some other parts of this code are complex, as shown below.

When used with an interactive python interpreter session, we want the api objects
to be self-descriptive for a much improved user learning curve; but at the same
time, we have to limit the amount of requests sent to the server for maintaining
a good performance.

All python api objects derive from class `APIObjectBase`, defined in file `base.py`.
This class defines the special method `__repr__()`, which is called to print
a representation of the python object.
See `https://docs.python.org/3/reference/datamodel.html#object.__repr__` for more
info. In our case, for a given object, we automatically print its attributes and
methods. If the attributes are themselves api objects, we recursively call their
`__repr__()` method but add a custom argument `level=1` to reflect the fact we
want a much shorter description this time.

To limit the amount of requests sent to the server, `APIObjectBase` also defines
the special method `__getattr__()`, allowing to retrieve the value of attributes
on-demand only, instead of retrieving the full knowledge as soon as the object
is created. The `__repr__()` method which has to display all attributes manages
a variable `self.__context__` allowing to send only one request to the server per
call.
Classes of higher level, such as the classes handling a set of nodes or a set of
images, also handle their own cache (in files `nodes.py` and `images.py`).

Handling the lifecycle of python objects is another important matter, that developers
should keep in mind. See this for instance:
```
>>> from walt.client import api
>>> vn7 = api.nodes.create_vnode("vn7")
Node vn7 is now booting your image "pc-x86-64-default".
Use `walt node boot vn7 <other-image>` if needed.
>>> vn7.remove(force=True)
>>> vn7
Traceback (most recent call last):
  [...]
  File "/root/walt-python-packages/.venv/lib/python3.11/site-packages/walt/client/apiobject/base.py", line 468, in __get_remote_info__
    self.__class__.__check_deleted__()
  File "/root/walt-python-packages/.venv/lib/python3.11/site-packages/walt/client/apiobject/base.py", line 458, in __check_deleted__
    raise ReferenceError("This item is no longer valid! (was removed)")
ReferenceError: This item is no longer valid! (was removed)
>>>
```
