# How to setup a WalT VPN HTTP entrypoint

## Introduction

Distant WalT nodes use a specific VPN boot procedure:
1. They download initial boot files (including a Linux kernel and an initial ramdisk) using HTTP requests to the VPN HTTP entrypoint and use them to boot;
2. While in the initial ramdisk code, they set up an SSH tunnel to the VPN SSH entrypoint and continue the boot procedure through that tunnel.

This documentation page explains how to set up the VPN HTTP entrypoint mentioned in step 1.
For step 2, see [`walt help show vpn-ssh-entrypoint`](vpn-ssh-entrypoint.md) instead.
And for more background information, see [`walt help show vpn`](vpn.md) and [`walt help show vpn-security`](vpn-security.md).


## Purpose of the VPN HTTP entrypoint

The VPN HTTP entrypoint is just a reverse HTTP proxy which redirects to the WALT server.
More precisely, all HTTP requests targetting `http://<http-entrypoint>/walt-vpn/<path>` must be proxied to `http://<walt-server>/walt-vpn/<path>`.
Obviously, if you want to deploy distant WalT nodes anywhere on internet, this HTTP proxy must be reachable from internet.


## Configuration examples

### Configuration of a VPN HTTP entrypoint based on NGINX

Given an existing NGINX installation, one should just add a new "NGINX site" defined as follows:
```
server {
    listen      80;
    listen      [::]:80;
    server_name <http-entrypoint>;

    location ^~ /walt-vpn/ {
        proxy_pass  http://<walt-server>/walt-vpn/;
    }
}
```

Replace `<http-entrypoint>` with the hostname the distant nodes will use to reach this proxy, and `<walt-server>` with the IP or hostname of the WalT server.


### Configuration of a VPN HTTP entrypoint based on Apache httpd

Given an existing Apache2 installation, one should just add a new "site" defined as follows:
```
<VirtualHost *:80>
    ServerName <http-entrypoint>
    ProxyPass "/walt-vpn/"  "http://<walt-server>/walt-vpn/"
</VirtualHost>
```

Replace `<http-entrypoint>` with the hostname the distant nodes will use to reach this proxy, and `<walt-server>` with the IP or hostname of the WalT server.

You may also need to enable modules `mod_proxy` and `mod_proxy_http` for the `ProxyPass` directive to work. It depends on the OS, but this usually means linking two more configuration files from the `mods-available` sub-directory to `mods-enabled`, in the configuration tree of Apache2.


### Configuration of a VPN HTTP entrypoint based on HAProxy

One should define the following configuration for HAProxy:
```
frontend walt-vpn-frontend
  bind :80
  acl vpn-host hdr(host) <http-entrypoint>
  acl vpn-path path_beg /walt-vpn/
  use_backend walt-vpn-backend if vpn-host vpn-path

backend walt-vpn-backend
  server walt-server <walt-server>:80
```

Replace `<http-entrypoint>` with the hostname the distant nodes will use to reach this proxy, and `<walt-server>` with the IP or hostname of the WalT server.


## Testing a newly installed VPN HTTP entrypoint

For testing the new HTTP entrypoint you have just set up, use the following command:
```
$ curl http://<http-entrypoint>/walt-vpn/server
```

It should return the hostname of the WalT server. If not, verify your network configuration and firewall.


## Updating the VPN HTTP entrypoint in WalT

To let WalT nodes use the newly installed VPN HTTP entrypoint, use `walt-server-setup --edit-conf`. The third interactive screen is the one about VPN settings. When you update the VPN HTTP entrypoint, an HTTP request will be automatically performed to verify your entry.

Once updated, the VPN nodes (Raspberry Pi 5 boards) will automatically reflash their EEPROM at next boot to take this change into account.
