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

