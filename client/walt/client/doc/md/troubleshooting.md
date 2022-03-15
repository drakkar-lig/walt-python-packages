
# Troubleshooting tips

## Issues with main WALT service

Most WALT features are handled on server-side by various `systemd` services.
The main service is called `walt-server`.

In case of problems with this service, `walt` command line tool most often prints the following error message:
```
$ walt node show
Network connection to WalT server failed!
$
```

The main service must listen are TCP ports 12345 and 12347 to handle `walt` client requests.
Thus this message most often means this main service is down.

You can verify this by running:
```
root@walt-server:~$ systemctl status walt-server
```

And you can check the systemd journal for this service by running:
```
root@walt-server:~$ journalctl -au walt-server
```

Usually the issue is minor, and you can restart the service by using:
```
root@walt-server:~$ systemctl restart walt-server
```

If this fails, then the issue is most often due to another server OS issue. See next section.


## Issues with other OS services

In order to list OS services which failed to start, run:
```
root@walt-server:~$ systemctl list-units --failed
```

Then you can check systemd journal for a given failing service by typing:
```
root@walt-server:~$ journalctl -au <failing-service>
```


## Issues with virtual nodes

For easier troobleshooting, virtual nodes are run using a `screen` command.
You can list screen session identifiers using:
```
root@walt-server:~$ screen -ls
```

And then connect to the session of the failing node using:
```
root@walt-server:~$ screen -r <session-id>
```

You may find the reason for the issue there.
If you need to scroll backward, type `ctrl-a` and then the `<esc>` key. This lets you enter the `Copy mode`: you can scroll using `<up>`, `<down>`, `<page-up`, and `<page-down>` keys. To leave the `Copy mode`, type `<esc>`.
To leave the screen session and return to the shell, type `ctrl-a` and then `<d>`.


## Reporting and asking for help

You can report new issues at https://github.com/drakkar-lig/walt-python-packages/issues.
If you have subscribed to [`walt-users`](https://listes.univ-grenoble-alpes.fr/sympa/subscribe/walt-users) mailing list, you can also send a message there.
You can also ask for help by sending an email to walt dev team: `walt-contact at univ-grenoble-alpes.fr`.

Try to include any relevant diagnosis data.
If the main service is working properly or you could restart it successfully, you can dump its log data to a file using:
```
$ walt log show --server --history -1h: > server.log
```

When the main service is working properly, this is usually more reliable than using `journalctl`.
This example will dump all log data about the previous hour. You can obviously adjust parameter `-1h:` to your case.
