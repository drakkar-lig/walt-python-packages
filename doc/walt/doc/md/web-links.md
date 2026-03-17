# Using the web links page

The page at `http://<walt-server>/links` lists the nodes and other devices
having port redirections defined throuph their `expose` configuration
setting.

For instance, let's consider one runs:
`walt node config vnode1 expose=80[label=website]`

In this case, a new list entry for node `vnode1` and a web link labelled
`website` will appear on this web page.
Adding the optional label allows to make the web link more descriptive
than just having the port number.

This web link targets `http://<walt-server>/links/vnode1/tcp/80`, which itself
redirects the browser to `http://<walt-server>:<server-port>`
(or `https://<walt-server>:<server-port>` if the web service appears to be
https-based), where `<server-port>` was selected automatically by the server.
Finally, the connection to `<walt-server>:<server-port>` is forwarded to
`vnode1:80`.

See [`walt help show device-expose`](device-expose.md) for more information
about configuring exposed ports.
