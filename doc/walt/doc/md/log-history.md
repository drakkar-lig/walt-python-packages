
# Displaying past logs

All logs are saved in a database on the walt server. You may retrieve them by using:
```
$ walt log show --history <range> [other_options...]
```

The `<range>` may be either `full`, `none`, or have the form
`[<start>]:[<end>]`.
Omitting `<start>` means the range has no limit in the past.
Omitting `<end>` means logs up to now should match.
Thus the range `:` is equivalent to using the keyword `full`.

If specified, `<start>` and `<end>` boundaries must be either:
- a relative offset to the current time, in the form `-<num><unit>`, such as `-40s`, `-5m`, `-1h`, `-10d` (resp. seconds, minutes, hours and days).
- the name of a checkpoint (see [`walt help show log-checkpoint`](log-checkpoint.md))
