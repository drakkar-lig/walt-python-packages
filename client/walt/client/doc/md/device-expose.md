
# Exposing the TCP port of a device

Commands `walt device expose` or `walt node expose` allow to expose the TCP port of a node or device
on the client machine.
This allows to access the network services they provide easily.

For instance, let us consider the node `rpi3b-webserver` is running a web server on port 80.
A user can run the following command:
```
$ walt node expose rpi3b-webserver 80 8088
Listening on TCP port 8088 and redirecting connections to rpi3b-webserver:80.
```

In this example we consider the user is using the `walt` command installed on the WalT server machine.
In this case the user can start its web browser and connect to URL `http://<walt-server>:8088`.
The web connexion will be redirected to `rpi3b-webserver:80` and will allow to display the
web interface served by the node.

This feature may also be applied to other devices of network `walt-net`, such as unmanaged devices
(cf. [`walt help show unmanaged-devices`](unmanaged-devices.md)), not only to WalT nodes.
