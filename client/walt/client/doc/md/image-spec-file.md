
# Writting image spec files

WalT images may optionaly provide a file `/etc/walt/image.spec`. Before the server exposes an image to nodes through NFS and TFTP, it will read this file and act accordingly. For now, the only feature available is the file templating system described below.

## File templating

Sometimes the content of some files embedded in an image should depend on the WalT platform where this image will be used. Here are a few examples:
* NTP client configuration requires to specify the IP address of the NTP server. In our case, the NTP server is the WalT server. As a result, this IP may vary depending on the WalT platform where the image is booted. (Note that we recommend using PTP rather than NTP, and PTP does not need this setting.)
* Bootup configuration files may also vary depending on parameters of WalT server. Actually, it is usually possible to rely on defaults; for example default server IP for NFS root filesystem is the IP of DHCP server, which is the WalT server too, so it can be omitted. Still, for specific needs, such as setting up the netconsole (send kernel bootup messages to WalT server as UDP packets), it is required to specify the mac address of the server.

In such cases, you can specify a spec file such as:

```
{
    "templates": [
        "<file_path>" [, "<file_path>" [...] ]
    ]
}
```

This file must be JSON-valid.

For example, in order to set up an appropriate NTP configuration, you could have:

```
[image-shell]$ cat /etc/walt/image.spec
{
    "templates": [
        "/etc/ntp.conf"
    ]
}
[image-shell]$
```

This indicates to the server that file `/etc/ntp.conf` should be considered a *template file*. As a result, the server will open it and look for the following two python-specific replacement patterns:
* `%(server_ip)s`
* `%(server_mac)s`

When such a pattern is found, it is replaced by the actual platform-specific value.

As a result, file `/etc/ntp.conf` could now contain:

```
[image-shell]$ cat /etc/ntp.conf
driftfile /var/lib/ntp/ntp.drift
[...]
server %(server_ip)s
[...]
[image-shell]$
```

These 2 files would make the NTP configuration valid on any WalT platform.

