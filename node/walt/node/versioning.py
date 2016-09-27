#!/usr/bin/env python
from walt.common.versions import API_VERSIONING, UPLOAD

def getnumbers():
    print repr((API_VERSIONING['NSAPI'][0], UPLOAD))

