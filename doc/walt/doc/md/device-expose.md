
# Exposing the TCP port of a device

WALT can expose the TCP port of a node or device on the server, or on the client machine.
This allows to access the network services they provide easily.

For instance, let us consider the node `rpi3b-webserver` is running a web server on port 80.

A user can run the following command:
```
$ walt node config rpi3b-webserver "expose=80:8088"
Done.
$
```

In this case the user can start its web browser and connect to URL `http://<walt-server>:8088`.
The web connexion will be forwarded to `rpi3b-webserver:80` and will allow to display the
web interface served by the node.

This port forwarding is permanent, unless this node configuration is modified again.
It will be properly restored when the walt server restarts.

One may specify several redirects at once (e.g., `expose=80:8088,443:8443`), and use 'none' to discard redirects previously configured.


WALT also provides an alternative way to redirect ports:
```
$ walt node expose rpi3b-webserver 80 8088
Listening on TCP port 8088 and redirecting connections to rpi3b-webserver:80.
```

This form of redirect has the following differences:
- The forwarding is managed by the `walt` client tool and will remain active
  up to ctrl-C.
- The forwarding port (8088 here) is now open on the machine where the `walt` client tool is run,
  which may or may not be the same machine as the WALT server.

This form is handy for a quick test but will be harder to automate in an experiment.
It may also be useful for people who use the `walt` client tool on a distant machine
(i.e., not on the server) and encounter network filtering problems with the previous setup.


Port forwardings may also be applied to other devices of network `walt-net`, such as unmanaged devices
(cf. [`walt help show unmanaged-devices`](unmanaged-devices.md)), not only to WalT nodes.
In this case, one should use `walt device config` (or `walt device expose` for the alternative method)
instead of `walt node config` (or `walt node expose`, repectively).

