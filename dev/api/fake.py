#!/usr/bin/env python

class FakePackage(object):
    def __init__(self, paths):
        self.__path__ = paths

class FakeMetaclass(type):
    OPERATORS = '__or__ __getattr__'.split(' ')
    def do_something(self, *args, **kwargs):
        return FakeObject

# all methods referenced in FakeMetaclass.OPERATORS will actually
# be assigned to FakeMetaclass.do_something
for op in FakeMetaclass.OPERATORS:
    setattr(FakeMetaclass, op, FakeMetaclass.do_something)

class FakeObject(object):
    __metaclass__ = FakeMetaclass
    '''Fake object that does nothing meaningful, but is designed
       to fool the calling code transparently.'''
    OPERATORS = '__or__ __call__ __getattr__'.split(' ')
    def __init__(self, *args, **kwargs):
        pass
    def do_something(self, *args, **kwargs):
        return FakeObject

# all methods referenced in FakeObject.OPERATORS will actually
# be assigned to FakeObject.do_something
for op in FakeObject.OPERATORS:
    setattr(FakeObject, op, FakeObject.do_something)

