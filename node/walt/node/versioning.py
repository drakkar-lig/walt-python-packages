#!/usr/bin/env python
from walt.common.versions import API_VERSIONING, UPLOAD

def getnumbers():
    print repr((API_VERSIONING['SERVER'][0], API_VERSIONING['NODE'][0], UPLOAD))

