
# Selecting log issuers

When using `walt log show` or `walt log wait` you may filter the log issuers considered by using:
```
$ walt log [show|wait] --issuers SET_OF_ISSUERS [other_options...]
```

`SET_OF_ISSUERS` can be for instance `rpi1`, `rpi1,rpi2`, `server` or `my-nodes` (see [`walt help show device-sets`](device-sets.md)).
The default value is `my-nodes`.

Notes:
- the server may generate log lines when important platform events occur.
- options `--nodes` and `--emitters` are obsolete aliases to `--issuers`.

