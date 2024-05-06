
# Repository: walt-python-packages; walt-server code.

This section explains various things helpful when modifying the walt server code.

As a reminder, this code is in subdirectory `server` of repository
`walt-python-packages`, and it must maintain a compatibility with python 3.9.
See [`walt help show dev-walt-python-packages`](dev-walt-python-packages.md) for information
regarding the whole repository.


## Systemd services

On a WALT server, systemd manages various services:
```
# systemctl list-units | grep walt | grep service | sed -e "s/.service//"
walt-server-dhcpd     loaded active running   WalT network DHCP daemon
walt-server-httpd     loaded active running   WalT server HTTP service
walt-server-lldpd     loaded active running   WalT LLDP server (based on lldpd)
walt-server-named     loaded active running   WalT network DNS service
walt-server-netconfig loaded active exited    WalT platform network management
walt-server-ptpd      loaded active running   WalT PTP server (based on ptpd2)
walt-server-snmpd     loaded active running   WalT SNMP server (based on snmpd)
walt-server-tftpd     loaded active running   WalT TFTP server (based on tftpd-hpa)
walt-server           loaded active running   WalT server daemon
#
```

The main daemon of the WALT platform is systemd unit `walt-server`. The underlying
executable started by this unit is `walt-server-daemon`. We will describe it in
details later.

When the OS boots or shutdowns, the network configuration specific to WALT is setup
or removed by systemd unit `walt-server-netconfig`, according to the content of
`/etc/walt/server.conf`.
Under the hood, it calls `walt-net-config up` or `walt-net-config down`.
The code is at `server/walt/server/netconfig.py`.

The other listed systemd units are network services. Except `walt-server-httpd`
which is a pure-python service, all those services internally rely on external
software:

| Unit name          | Underlying binary  | Related apt package |
|--------------------|--------------------|---------------------|
| walt-server-dhcpd  | /usr/sbin/dhcpd    | isc-dhcp-server     |
| walt-server-lldpd  | /usr/sbin/lldpd    | lldpd               |
| walt-server-named  | /usr/sbin/named    | bind9               |
| walt-server-ptpd   | /usr/sbin/ptpd     | ptpd                |
| walt-server-snmpd  | /usr/sbin/snmpd    | snmpd               |
| walt-server-tftpd  | /usr/sbin/in.tftpd | tftpd-hpa           |

When installing WALT, the default systemd service installed with each apt package is
disabled, and the relevant WALT-specific service is installed instead: the unit file
is copied from `server/walt/server/setup/<unit>.service` to `/etc/systemd/system/`.
Each WALT-specific service actually just reuses the binary, but it does not touch
the default configuration provided with the apt packet. Instead, configuration files
specific to WALT are generated in `/var/lib/walt/services/<service-name>/*` and the
binary is called with the appropriate option to find it there.

Some of these WALT services also redirect the working directory to
`/run/walt/<service-name>/`, for instance to store a PID file.

Note: if we were modifying the default configuration files, it would complexify OS
upgrades with questions such as "Should we overwrite this file you modified with the
one embedded in the new version of the packet?".

In the case of `lldpd`, `ptpd`, `snmpd` and `tftpd`, computing the exact command line
options of the binary requires specific processing.
For instance regarding `lldpd` we need to specify the IP of interface walt-net using
option `-m <ip>` for the service to listen on it, and retrieving this IP requires
reading `/etc/walt/server.conf`.
In this case, the systemd unit WALT installs does not refer to the binary directly.
Instead, it calls an executable `walt-server-<service>` (e.g., `walt-server-lldpd`),
which computes the full options and then starts the binary using `os.execvp()`.
The python code of those executables is at `server/walt/server/services/`.


## Other python or shell commands

The python package `walt-server` installs various executables, as shown in sections
`console_scripts` and `scripts` in `dev/metadata.py`.

Apart from the executables already mentioned in previous section, we have:

| Executable                    | Purpose                                            |
|-------------------------------|----------------------------------------------------|
| walt-server-setup             | Install or Upgrade the WALT server                 |
| walt-server-trackexec-replay  | Trackexec replay tool                          (1) |
| walt-server-trackexec-analyse | Trackexec analysis tool                        (1) |
| walt-dhcp-event               | walt-server-dhcpd -> walt-server notifications (2) |
| walt-server-cleanup           | ExecStartPre directive of walt-server.service  (3) |

(1): See [`walt help show trackexec`](trackexec.md).

(2): In the file `dhcpd.conf`, we specify that for each new IP lease, the dhcpd service
must run `walt-dhcp-event` (with device ip, mac, vendor class identifier, etc.,
indicated as parameters). This python executable connects to walt-server-daemon and
calls `SSAPI.register_device(<parameters>)`. This API is defined at
`server/walt/server/processes/main/api/ss.py`. By this way, `walt-server-daemon` can
detect new devices or nodes. Note: `SS` stands for "Server to Server", since both
processes are running on the server.

(3): If ever `walt-server-daemon` crashes, it could let the system in a dirty state,
for instance with podman containers still running or walt images still mounted.
On next call to `systemctl start walt-server`, `walt-server-cleanup` will try to
clean things up before `walt-server-daemon` starts again.

The remaining executables mentionned in `dev/metadata.py` are helper scripts of
`walt-server-daemon`.

In case you need to modify one of these commands, refer to `dev/metadata.py` to
know where the code is.


## walt-server-daemon

`walt-server-daemon` is the most important process running on the server. It implements
the core logic of a WALT server: it is responsible for mounting WALT images and
exporting them through NFS, updating TFTP symlinks for the nodes to boot the
appropriate image, saving platform and experiment logs, replying to requests from the
`walt` client tool or its `api` object, interacting with the docker hub or a custom
registry, communicating with network switches for network discovery or PoE reboots,
and many other things.


### Debugging options

For a quick debug session:

1. Insert a line `import pdb; pdb.set_trace()` at the place you want to debug
2. Update the venv with your modifications: run `make quick-venv-update`
3. Get rid of systemd: run `systemctl stop walt-server`
4. Start the service yourself: run `walt-server-daemon`

The service will stop with a pdb prompt at the place you inserted `pdb.set_trace()`.

You can also enable **trackexec** to record the execution path of `walt-server-daemon`
subprocesses and later analyse any unexpected behavior by using
`walt-server-trackexec-replay`. See [`walt help show trackexec`](trackexec.md).


### walt-server-daemon subprocesses

The code of `walt-server-daemon` is at `server/walt/server/daemon.py`. It actually
starts and connects the following 4 sub-processes:
* `server-main`: the most important one, managing most features.
* `server-hub`: the process receiving RPC calls (remote-procedure-calls) from clients,
  nodes, or other server processes, and transmitting them to `server-main`.
* `server-db`: the process interacting with the WALT server database.
* `server-blocking`: a process used for long running tasks.

`server-hub` is connected to `server-main` only.
`server-main` is connected to the 3 others.
Both `server-main` and `server-blocking` interact with `server-db` for managing the
database.

We avoid multi-threading: each of these subprocesses handle tasks one at a time.
Considering `server-main`, `server-hub`, and `server-db`, it is important to avoid
blocking the process too long. Some long blocking tasks are delegated to
`server-blocking` (for instance, the communication with network switches), or
to other short-lived subprocesses, for this reason.

The code of each subprocess is at `server/walt/server/processes/<name>`.


### Connectors between subprocesses

The connector between two sub-processes is a complex object, but its usage is
straightforward.

It may be used synchronously, such as this code in `processes/main/nodes/manager.py`:
```
for node in self.db.select("devices", type="node"):
    [...]
```
In this case, `self.db` is `server-main`'s connector for interacting with `server-db`.

This code is very readable, but be careful, it is more subtle than it seems: during
this kind of synchronous call, the calling process (`server-main` here) returns to
its event loop, for managing any unrelated task which may arrive in the meantime.
So be careful with code reentrance.

Connectors may also be used asynchronously, such as in this code:
```
self.db.do_async.insert_multiple_logs([...])
```
Since inserting a batch of logs may take a little time, and we do not have to wait
for a return value, we specify `do_async`: `server-main` will **not** wait for this
remote task to complete before jumping to the next instruction.
Note however that since `server-db` is also running one task at a time, if `server-main`
uses a synchronous db request shortly after this one, a small delay may occur.


### Event loop

The daemon and each subprocess is managed by an event loop (source code at
`common/walt/common/evloop.py`).

Basically the code works by plugging "listener objects" on the event loop. Each
listener is responsible for managing a given file descriptor, which may be
the socket connected to a client, a server socket waiting for connections,
the underlying pipe of a connector between two subprocesses, etc. The listener
provides a method `fileno()` which returns this file descriptor, a method
`handle_event()` called when the event loop detects an event related to this
file descriptor, and a method `close()` for cleaning up.

A new listener is plugged on the event loop by using:
`ev_loop.register_listener(<listener>)`.
If the listener has completed its work or detected a problem, the call to its
method `handle_event()` should return `False`. In this case, the event loop
will call `<listener>.close()` and automatically remove `<listener>` from its set
of listeners.

The event loop also handles planning events at a given time (look for calls to
`plan_event()`), and simplifies running parallel shell or python commands (look for
calls to `ev_loop.do()` and `ev_loop.auto_waitpid()`).


### Other "pluggable" objects

Similarly to the event loop, the subclasses of `GenericServer`, such as `TCPServer` or
`UnixServer` (both implemented in `walt-common`) accept various kind of requests by
plugging appropriate "listener classes". When a client connects to this kind of
generic server, it sends a request ID which the server uses to know which listener
class should be instanciated to process the request.


### External RPC APIs

For communicating with `walt-server-daemon`, clients, nodes and external server
processes (such as `walt-dhcp-event`) can connect to TCP port 12345 for
remote-procedure-call (RPC) type of communication.

TCP port 12345 is opened by `server-hub`. Requests are forwarded to `server-main`
and are implemented in `server/walt/server/processes/main/api/<api>.py`.

Four RPC APIs are implemented:
* cs.py: Client to Server API (handling the many client requests)
* ns.py: Node to Server API (e.g., method `sync_clock()` is there)
* ss.py: Server to Server API (e.g., method `register_device()` called by
  `walt-dhcp-event`, a process running on the server too)
* vs.py: Virtual to Server API (handles calls from executables of
  package `walt-virtual`)

It is important to keep in mind the different compatibility requirements for
these API files.
Modifying an API call in `ss.py` is never a problem since the caller is also
installed on the server, so we know that its code will be updated at the same
time.
Modifying an API call in `cs.py` is also fine because the client verifies
that server and client WALT version are the same when connecting to the API.
Modifying `ns.py` should be carefully thought because old WALT images embedding
`walt-node` code must continue working; similarly, some of the API calls at
`vs.py` are useful for VPN nodes already deployed.

For an example of how to use this RPC endpoint from client code, checkout
[`walt help show dev-client`](dev-client.md).

Note that while processing those API calls, the server may itself perform API calls
the other way (server to client), such as `requester.stdout.write()` or
`requester.get_username()`. The client itself exposes a local RPC API to manage this
at `client/walt/client/link.py`.


### External TCP stream API

Clients and nodes can also connect to server TCP port 12347 for stream based
communication features.
TCP port 12347 is opened by `server-main` and is managed by a `TCPServer` object
(see "Other pluggable objects" above): the remote peer writes a request ID just
after connecting in order to let the server know which kind of processing is
expected.
This channel is used by the nodes to publish experiment logs for instance.
It is also used by the client for file transfers (`walt node cp`, etc.),
remote shells (for instance `walt image shell`), etc.

For an example of how to use this TCP stream API endpoint from client code, checkout
[`walt help show dev-client`](dev-client.md).


### Server database

The server database is managed by subprocess `server-db`, using library `psycopg2`.
For more information about the database itself, see [`walt help show dev-server-db`](dev-server-db.md).


### Workflow objects

Subprocess `server-main` makes frequent use of a class called `Workflow`.
It is implemented in `server/walt/server/processes/main/workflow.py`.

For understanding the purpose of this class, let us consider the case of rebooting
nodes. It is actually a complex process involving several kinds of callbacks called
after very diverse wait conditions.

* On node-side, "soft reboot" is based on a minimal busybox-based network service.
  The server relies on it to request a reboot, but communication should not block
  the whole process (so internally the function works with the event loop and a
  non-blocking socket).
* "Hard rebooting" nodes using PoE involves sending a request to the switch to stop
  powering the PoE port (this is implemented as an async RPC call to `server-blocking`,
  with a callback in charge of continuing this procedure), then waiting for a little
  time (this involves a call to `ev_loop.plan_event()`), then restoring the power
  (again, by relying on `server-blocking`).

Without a Workflow object, going from one step to the next one would involve a set
of callbacks and would be very hard to follow.

As shown in file `server/walt/server/processes/main/nodes/reboot.py`, the Workflow
class allows to clarify the suite of steps to perform:
```
    wf = Workflow(
        [
            wf_soft_reboot_nodes,
            wf_hard_reboot_virtual_nodes,
            wf_hard_reboot_nodes,
            wf_reply_requester,
        ],
        **env
    )
    wf.run()
```

If needed, one of the steps involved may call `wf.insert_steps()` to further split
the procedure in smaller logical pieces, without complexifying this high-level view.

Each workflow step is defined as a function (or method, with `self` added as first
argument) written like this:
```
def wf_<func-name>(wf, <named-args-used-in-the-function,...>, **env):
    [...]
```

The environment `env` is initialized when the Workflow is created (see above).
Some workflow steps may alter the environment when needed by using `wf.update_env()`.

The workflow continues with the next step when `wf.next()` is called.
It is the responsability of each workflow step to call `wf.next()`, either directly,
or by planning such a call later, by specifying `wf.next` as a callback somewhere.
See function `wf_poe_poweron` in the same file for instance.

In case of an unrecoverable issue, a workflow step may use `wf.interrupt()` instead,
which will explicitely stop the whole workflow.

If ever a call to `wf.next()` or `wf.interrupt()` is missing, the Workflow
object will print an error message when garbage collected, indicating how many
remaining steps where missed, in order to help the developer fix the issue.
