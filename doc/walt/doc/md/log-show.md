
# How to query & display experiment logs

The main entrypoint to display experiment logs is subcommand `walt log show`.
Two kinds of logs exist: platform logs and experiment logs.
For more information about these walt logging features, or about walt logging concepts (log lines, log streams,
log issuers, log checkpoints), checkout [`walt help show logging`](logging.md).

Command `walt log show` has two modes of operation:
* option `--history` to display past logs (see [`walt help show log-history`](log-history.md))
* option `--realtime` to display logs in real time (see [`walt help show log-realtime`](log-realtime.md))

At least one of these options must be present.
Selecting both of them is allowed too. For instance, the following command first displays log lines
generated less than 30 seconds ago and then continues by displaying new log lines in realtime:
```
$ walt log show --history -30s: --realtime --platform
```

Command `walt log show` can filter logs in various ways:
* specify a regular expression which will be matched against the content of log lines (as the last positional argument)
* option `--issuers`: specify which device(s) emitted the log lines (see [`walt help show log-issuers`](log-issuers.md))
* option `--streams`: specify which log stream(s) should be displayed (as a regular expression)

Option `--format` allows to change the way log lines are printed (see [`walt help show log-format`](log-format.md)).

