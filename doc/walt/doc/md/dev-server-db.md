
# WalT server database

The section describes the database used by the WALT server.

## General information

The database management system is `postgresql`.
The systemd service name depends on the potgresql version, but you can type the
following to find it:
```
$ systemctl status postgresql*main.service
```

All interaction is performed by subprocess `server-db` of `walt-server-daemon`.
See [`walt help show dev-server`](dev-server.md) for more information about
those python processes.


## Initialization code

WALT uses the defaut configuration of postgresql, unchanged.

However, the first time `walt-server-daemon` is started, it performs the following:
* create a database user called `root`
* create a database called `walt` and owned by `root`
* create the tables and indexes

The relevant code is in `server/walt/server/processes/db/postgres.py` and
`server/walt/server/processes/db/db.py`.

In case of a WALT version upgrade, the startup code in `db.py` may also perform a few
modifications to the table and indexes when restarted for the first time.


## Postgresql upgrades

When an OS upgrade is needed, `walt-server-setup` takes care of upgrading
the WALT database to the new version of postgresql.


## Connecting to the database, for debugging

When connected as root@walt-server, one can connect to the database using:
```
# psql walt
psql (15.6 (Debian 15.6-0+deb12u1))
Saisissez « help » pour l'aide.

walt=>
```

By default, postgresql configuration allows connecting without a password when
the OS user matches the database user; this is what happens here.

Alternatively, you can use `walt advanced sql`.


## Basic postgresql usage tips

To list database tables use:
```
walt=> \dt
[...]
```

For details about a given table (columns, primary and foreign keys, indexes), use:
```
walt=> \d <table-name>
[...]
```

You can also obviously run SQL queries.


## Notes about walt tables

The central table is `devices`. It gives the mac, ip, name, type and config of all
devices detected on the network. Those devices include the nodes (`type='node'`),
the server itself (`type='server'`), the network switches (`type='switch'`), and
the other devices (`type='unknown'`).
The primary key is `mac`, and it is referenced by foreign key constraints on most of
the other tables.

Nodes have a dedicated table indicating which image they boot, their model
(e.g. `rpi-2-b`) and a foreign key to `devices.mac`.

Switches also have a dedicated table.

Table `images` is a list of walt images (i.e. images in the registry managed by
`podman` on the server).

Table `switchports` indicates the switch port names the user configured using
`walt device port-config`.

Table `poeoff` indicates the reason why PoE is currently disabled on a given
switch port (can be 'powersave', 'poe-reboot', etc). This information is relevant
only until PoE is restored on the switch port; at this time, the table row is
removed. It is useful for instance to avoid attempting soft-reboot when the node
already has PoE off; and for the server to restore its knowledge about PoE status
when restarting.

Table `topology` indicates current network topology knowledge. Flag `confirmed`
is `true` only for the switch neighbors found at last `walt device rescan`.
Devices detected by older scans but not the last one have `confirmed=false`.
The neighboring relationship is symetric, so the table has two pairs of columns
`(switch1, port1)` and `(switch2, port2)`. Depending on the protocol, `port1`
and `port2` may not be known; in this case their value is NULL.

Table `logs`, `logstreams` and `checkpoints` refer respectively to the log lines,
log streams and log checkpoints. See [`walt help show logging`](logging.md) for more info.
Column `logs.stream_id` is a foreign key refering to `logstreams.id`.


## Connecting to the database, as admin

The real admin user of potsgresql is user `postgres`.
If ever you need it, you can connect as `postgres` using:
```
# su -c psql -l postgres
```
With this user, you can for instance create another database user, give it
read-only access to walt tables, and use it to connect an external reporting or
graphing tool. This is out of scope of this documentation.
