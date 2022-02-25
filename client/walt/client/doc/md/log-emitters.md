
# Selecting log emitters

When using `walt log show` or `walt log wait` you may filter the log emitters considered by using:
```
$ walt log [show|wait] --emitters SET_OF_EMITTERS [other_options...]
```

`SET_OF_EMITTERS` can be for instance `rpi1`, `rpi1,rpi2`, `server` or `my-nodes` (see [`walt help show device-sets`](device-sets.md)).
The default value is `my-nodes`.

Notes:
- the server may generate log lines when important platform events occur.
- option `--nodes` is an obsolete alias to `--emitters`.

