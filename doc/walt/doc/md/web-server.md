# Web server

The web server is one of the components installed on your WALT server.
It is available on default port 80, so you can point your browser at
`http://<walt-server>` to reach it.

The web server component currently provides the following features:
* [/api](/api): the web API (see [`walt help show web-api`](web-api.md))
* [/doc](/doc): the documentation for your current version of WALT,
  formatted like https://walt.readthedocs.io
* [/links](/links): quick links to exposed ports of nodes and devices
  (see [`walt help show web-links`](web-links.md))
* `/boot`: boot file transfer services, used by some node bootloaders as
  an alternative to TFTP.
