# -*- coding: utf-8 -*-
explorer = None

def register_api_explorer(expl):
    global explorer
    explorer = expl

# mark methods to be exposed by replacing them by
# an instance of APIExposedMethod class.
# (we cannot rename these attributes here, their 'name'
# belongs to the class. That's why we need
# the other decorator @api below.)
class APIExposedMethod(object):
    def __init__(self, func):
        self.func = func

def api_expose_method(func):
    return APIExposedMethod(func)

# given an __init__ constructor and a set of
# attributes that must be exposed, compute a decorated
# __init__ function, that will rename the attrs at the
# end of the provided constructor.
class APIDecoratedInit(object):
    def __init__(self, attrs, init_func):
        self.attrs = attrs
        def decorated_init_func(obj, *args, **kwargs):
            init_func(obj, *args, **kwargs)
            for attr in attrs:
                val = getattr(obj, attr)
                setattr(obj, 'exposed_' + attr, val)
        self.decorated_init = decorated_init_func

# return a decorator to be applied to an __init__ function
# and able to handle a list of attributes that must be exposed.
def api_expose_attrs(*attrs):
    def decorator(init_func):
        return APIDecoratedInit(attrs, init_func)
    return decorator

# expose class attributes specified.
def api_expose_class_attrs(*c_attrs):
    def decorator(cls):
        for c_attr in c_attrs:
            if explorer:
                explorer.add_attr(cls, c_attr)
            val = getattr(cls, c_attr)
            setattr(cls, 'exposed_' + c_attr, val)
        return cls
    return decorator

# Behavior in production code:
# loop through attributes of the class...
# * look for any instance of class APIExposedMethod,
# replace these by the original method, and
# duplicate them by prefixing 'exposed_'
# * look for any instance of class APIDecoratedInit,
# replace these by the decorated __init__
#
# Behavior when exploring the API:
# dump the prototype of the exposed methods and
# the name of the exposed attributes.
def api(cls):
    for k, v in list(cls.__dict__.items()):
        if isinstance(v, APIExposedMethod):
            if explorer:
                explorer.explore_method(cls, v.func)
            setattr(cls, k, v.func)
            setattr(cls, "exposed_%s" % k, v.func)
        elif isinstance(v, APIDecoratedInit):
            if explorer:
                for attr in v.attrs:
                    explorer.add_attr(cls, attr)
            setattr(cls, k, v.decorated_init)
    return cls

