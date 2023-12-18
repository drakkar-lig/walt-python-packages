
# Transfering files to or from a walt image

`walt image cp` allows to transfer files to or from a walt image.
Its interface is very similar to `scp`, but simplified. Two forms are allowed:
```
$ walt image cp <image>:<path> <local-path>
$ walt image cp <local-path> <image>:<path>
```

Notes:
- You can transfer files or directories the same way (no specific option is needed for directories).
- Second form modifies the image. Thus it will trigger a reboot of all nodes which have booted this image.
- Command `walt node cp` modifies an image too when using keyword `booted-image` (see [`walt help show node-cp`](node-cp.md)).
