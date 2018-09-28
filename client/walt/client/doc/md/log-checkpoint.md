
# log checkpoints

A checkpoint is a kind of marker in time. It allows to easily reference the associated point in time by just giving its name.

Here is a sample workflow:
```
$ walt log add-checkpoint exp1-start
[... run experience exp1 ...]
$ walt log add-checkpoint exp1-end
$ walt log show --history exp1-start:exp1-end > exp1.log
```

By using `walt log add-checkpoint` with option `--date`, you can also create a checkpoint referencing a given date. For example:
```
$ walt log add-checkpoint --date '2015-09-28 15:16:39' my-checkpoint
```

For the sake of completeness, commands `walt log list-checkpoints` and `walt log remove-checkpoint` are also provided, and their use should be obvious.
