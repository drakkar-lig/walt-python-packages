#!/usr/bin/env python
def update(status):
    with open('/run/walt-status', 'w') as f:
        f.write('%s\n' % status)
