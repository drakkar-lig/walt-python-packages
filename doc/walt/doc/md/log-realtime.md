
# Displaying logs in realtime

WalT logs may be retrieved in pseudo-realtime by using:
```
$ walt log show --realtime [other_options...]
```

In this mode, `walt log show` will wait for incoming log records and display them.

Note that you may combine `--realtime` and [`--history`](log-history.md) options, e.g.:
```
$ walt log show --history '-2m:' --realtime
```
This will display the logs from 2 minutes in the past to now and then continue listening for new incoming logs.
