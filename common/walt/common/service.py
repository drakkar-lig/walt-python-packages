import rpyc, inspect

# This decorator allows to define RPyC service classes
# with a customized __init__ function.
# (without it, one has to conform to the prototype of the base
# class rpyc.Service.__init__(), because the rpyc core
# instanciates such a service itself.)
def RPyCService(cls):
    # caution: cls must be the first base class in order to be
    # first in the method resolution order (e.g. regarding on_connect()).
    def mixed_cls_generator(*cls_args, **cls_kwargs):
        class Mixed(cls, rpyc.Service):
            def __init__(self, *args, **kwargs):
                rpyc.Service.__init__(self, *args, **kwargs)
                cls.__init__(self, *cls_args, **cls_kwargs)
        return Mixed
    return mixed_cls_generator

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
        # discard the 'exposed_' prefix
        attr = attr[8:]
        try:
            if not hasattr(self.remote_obj, attr):
                return None
            obj = getattr(self.remote_obj, attr)
            if inspect.ismethod(obj):
                # recursively return a proxy for this method
                return RPyCProxy(obj, self.ignore_spec)
            else:
                return obj
        except self.ignore_spec:
            return None
    def __call__(self, *args, **kwargs):
        # if we are here, the remote object should also be callable...
        # call it and return the result.
        try:
            return self.remote_obj(*args, **kwargs)
        except self.ignore_spec:
            return None

