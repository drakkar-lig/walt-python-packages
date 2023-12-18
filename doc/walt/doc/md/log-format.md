
# Adapting log display format

You may display walt logs in a custom format by using:
```
$ walt log show --format FORMAT_STRING [other_options...]
```

`FORMAT_STRING` should be a python-compatible string formating pattern.
The default is: `'{timestamp:%H:%M:%S.%f} {issuer}.{stream} -> {line}'`

A useful example in case of batch processing is to use `'{timestamp:%s.%f}'` for the timestamp part. It will be displayed as a POSIX timestamp (i.e. a float number of seconds since Jan 1, 1970).
