# -*- coding: utf-8 -*-
explorer = None

def register_api_explorer(expl):
    global explorer
    explorer = expl

class api_expose(object):
    def __init__(self, func):
        self.func = func

def api(cls):
    for k, v in list(cls.__dict__.items()):
        if isinstance(v, api_expose):
            if explorer:
                explorer.explore_method(cls, v.func)
            delattr(cls, k)
            setattr(cls, "exposed_%s" % (k,), v.func)
    return cls

