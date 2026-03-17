
# Exposing the TCP port of a device

WALT can expose the TCP port of a node or device on the server, or on
the client machine.
This allows to access the network services they provide easily.


## Using `walt node config`

For instance, let us consider the node `rpi3b-webserver` is running a web server on port 80.

We can "expose" this port by running the following command:
```
$ walt node config rpi3b-webserver "expose=80:4080"
Done.
$
```

With this command, the WalT server starts to listen for new connections
on its TCP port 4080, and redirects them to port 80 of `rpi3b-webserver`.
After that, we can start a web browser and connect to URL
`http://<walt-server>:4080` to display the web interface served by the node.

We can also let the WalT server choose a TCP port:
```
$ walt node config rpi3b-webserver "expose=80"
Done.
$
```

If needed we can check which TCP port was selected by typing
`walt node config rpi3b-webserver` again and looking for the fully
resolved setting `expose=80:<server-port>`.

However, in such a case where the service on the node is a web interface,
we have more direct alternatives. We can directly:
* Point our browser to `http://<walt-server>/links` and click on the
  appropriate link;
* Or directly use a shortcut URL:
  `http://<walt-server>/links/rpi3b-webserver/tcp/80`.

See [`walt help show web-links`](web-links.md) for more info.

Additionnal notes:
* This port forwarding is permanent, unless this node configuration is
  modified again. It will also be properly restored when the walt server
  restarts.
* One may use a label to better identify an exposed port, using the syntax
  `expose=80[label=webapp]` for instance, or `expose=80:4080[label=webapp]`
  if the server port is specified. The label will be displayed on the web
  page at `http://<walt-server>/links`. A label should only contain
  lowercase characters and dashes.
* One may specify several redirects at once (e.g., `expose=80,443`, or
  `expose=80[label=website],8088:6888[label=debug]`).
* One may configure several nodes at once too
  (e.g., `walt node config vnode1,vnode2 expose=80`).
* One should use `expose=none` to discard redirects previously configured.
* When using a shortcut URL such as
  `http://<walt-server>/links/<device-name>/tcp/<device-port>`, always
  specify `http` and not `https`, even if the service at
  `<device-name>:<device-port>` is https-based. The code handling
  this shortcut URL will auto-detect the proper protocol and redirect
  your browser properly.


## Using `walt node expose` (alternate method)

WALT also provides an alternative way to redirect ports:
```
$ walt node expose rpi3b-webserver 80 8088
Listening on TCP port 8088 and redirecting connections to rpi3b-webserver:80.
```

This form of redirect has the following differences:
- The forwarding is managed by the `walt` client tool and will remain active
  up to ctrl-C.
- The forwarding port (8088 here) is now open on the machine where the
  `walt` client tool is run, which may or may not be the same machine as
  the WALT server.

This form is handy for a quick test but will be harder to automate in an
experiment. It may also be useful for people who use the `walt` client tool
on a distant machine (i.e., not on the server) and encounter network
filtering problems with the previous setup.


## Using port forwarding with other devices

Port forwardings may also be applied to other devices of network `walt-net`,
such as switches or unmanaged devices
(cf. [`walt help show unmanaged-devices`](unmanaged-devices.md)), not only
to WalT nodes.
In this case, one should use `walt device config` (or `walt device expose`
for the alternative method) instead of `walt node config` (or
`walt node expose`, repectively).
