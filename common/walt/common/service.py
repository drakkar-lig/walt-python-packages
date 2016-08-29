import rpyc

# This decorator allows to define RPyC service classes
# with a customized __init__ function.
# (without it, one has to conform to the prototype of the base
# class rpyc.Service.__init__(), because the rpyc core
# instanciates such a service itself.)
def RPyCService(cls):
    class Wrapper(rpyc.Service, cls):
        def __init__(self, *args, **kwargs):
            cls.__init__(self, *args, **kwargs)
        def __call__(self, *args, **kwargs):
            rpyc.Service.__init__(self, *args, **kwargs)
            return self
    return Wrapper

# This class allows to build RPyC proxies for the following scenario:
# process1 <--rpyc-link--> process2 <--rpyc-link--> process3
# If process2 wants to expose objects of process1 directly to process3,
# it will not work directly because of the 2 layers of 'exposed_' prefixes.
# In this case it should return RPyCProxy(<object>) instead.
class RPyCProxy(object):
    def __init__(self, remote_obj, path=(), ignore_spec=()):
        self.remote_obj = remote_obj
        self.path = path
        self.ignore_spec = ignore_spec
    def __getattr__(self, attr):
        if not attr.startswith('exposed_'):
            return None
        else:
            # discard the 'exposed_' prefix,
            # recursively return a proxy for this attr
            return RPyCProxy(   self.remote_obj,
                                self.path + (attr[8:],),
                                self.ignore_spec)
    def __call__(self, *args, **kwargs):
        # if we are here, the remote object should also be callable...
        # call it and return a proxy for the result.
        try:
            path = self.path
            remote_obj = self.remote_obj
            while len(path) > 0:
                remote_obj = getattr(remote_obj, path[0])
                path = path[1:]
            return RPyCProxy(remote_obj(*args, **kwargs), (), self.ignore_spec)
        except self.ignore_spec:
            pass

