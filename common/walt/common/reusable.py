import weakref, threading, atexit

# This allows to define the 'reusable' decorator.
# You can try for instance:
#
# @reusable
# class C(object):
#     def __init__(self, t):
#         self.t = t
#         print t
#     def __del__(self):
#         print 'del', self.t
#
# c = C(3)
# c = C(3)
# c = C(4)
# c = C(4)
# c = None
#
# When decorated this way, if its constructor is invoked twice
# with the same arguments, the same object will be found in
# cache and returned.

class ReusePool(object):
    def __init__(self, cls):
        self.cls = cls
        self.pool = {}
    def get(self, *args, **kwargs):
        argdesc = args, tuple(kwargs.items())
        if argdesc in self.pool:
            obj = self.pool[argdesc]
        else:
            obj = self.cls(*args, **kwargs)
            self.pool[argdesc] = obj
        return obj

def reusable(cls):
    pool = ReusePool(cls)
    # we decorate a class but we return a function:
    # what seems to be a call to the class constructor
    # will actually be a call to this function.
    def func(*args, **kwargs):
        return pool.get(*args, **kwargs)
    return func


