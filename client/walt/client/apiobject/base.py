import socket, inspect
from contextlib import contextmanager

class CommentedString(str):
    def __new__(cls, s, comment):
        instance = super().__new__(cls, s)
        instance._comment = comment
        return instance
    def __repr__(self):
        return super().__repr__() + '  # ' + self._comment

def short_repr(obj):
    if isinstance(obj, APIObjectBase):
        return obj.__repr__(level=1)
    elif isinstance(obj, list):
        return '[' + ', '.join(short_repr(elem) for elem in obj) + ']'
    elif isinstance(obj, Exception):
        return '<' + str(obj) + '>'
    else:
        res = repr(obj)
        if len(res) > 70:
            res = res[:67] + '...'
        return res

def get_attrs_desc(obj):
    # regular attributes
    attrs = { k: v for k, v in obj.__doc_attrs__() }
    # properties
    for attr_name, attr_val in inspect.getmembers(obj.__class__, inspect.isdatadescriptor):
        if attr_name.startswith('_'):
            continue
        try:
            attrs[attr_name] = getattr(obj, attr_name)
        except socket.error:
            raise   # probably a connection error with hub
        except Exception as e:
            attrs[attr_name] = e
    if len(attrs) == 0:
        return (), ''
    return attrs.keys(), '\n  attributes:\n' + '\n'.join(
        '  - self.' + str(k) + ': ' + short_repr(v) for k, v in sorted(attrs.items())) + '\n'

def get_methods_desc(obj, excluded_attrs):
    # we cannot directly use inspect.getmembers(obj, inspect.ismethod)
    # because it would cause evaluation of properties, and evaluation of properties
    # may throw exceptions.
    method_names = []
    for attr in obj.__dir__():
        if attr.startswith('_') or attr in excluded_attrs:
            continue
        val = getattr(obj, attr)
        if inspect.ismethod(val):
            method_names.append(attr)
    res = ''
    if len(method_names) > 0:
        res += '\n  methods:\n'
        for method_name in sorted(method_names):
            method = getattr(obj.__class__, method_name)
            res += '  - self.' + method.__name__ + str(inspect.signature(method)) + \
                   ': ' + method.__doc__ + '\n'
    return res

def get_preview_desc(obj):
    if hasattr(obj, '_preview'):
        return '\n  preview:\n  ' + '\n  '.join(obj._preview.splitlines()) + '\n'
    else:
        return ''

def get_subitem_accessor(k):
    if isinstance(k, str):
        return 'self.' + k
    else:
        return 'self[' + repr(k) + ']'

def get_subitems_desc(obj):
    items = list(obj.__doc_subitems__())
    if len(items) == 0:
        return ''
    return '\n  sub-items:\n' + '\n'.join(
        '  - ' + get_subitem_accessor(k) + ': ' + short_repr(v) for k, v in sorted(items)) + '\n'

class APIObjectBase:
    def __init__(self):
        self.__context__ = None
    def __get_remote_info__(self):  # overwrite in subclass
        return {}
    def __doc_subitems__(self):     # overwrite in subclass if needed
        return ()
    @property
    def __dynamic_doc__(self):      # overwrite in subclass if needed
        return self.__class__.__doc__ # return the docstring of the class by default
    def __doc_attrs__(self):        # overwrite in subclass if needed
        return self.__buffered_get_info__().items()
    def __repr_context__(self):
        @contextmanager
        def cm():
            try:
                self.__context__ = {}
                yield
            finally:
                self.__context__ = None
        return cm()
    def __repr__(self, level=0):
        with self.__repr_context__():
            short_desc = self.__dynamic_doc__
            if level == 1:
                return '<' + short_desc + '>'
            elif level == 0:
                attr_names, attr_desc = get_attrs_desc(self)
                res = '< -- ' + short_desc + ' --\n'
                res += attr_desc
                res += get_methods_desc(self, excluded_attrs = attr_names)
                res += get_subitems_desc(self)
                res += get_preview_desc(self)
                res += '>'
            return res
    def __buffered_get_info__(self):
        # it's expensive to request several times info() on remote object,
        # so if we have a running context, save it there
        if self.__context__ is not None:
            if 'info' in self.__context__:
                return self.__context__['info']
        info = self.__get_remote_info__()
        if self.__context__ is not None:
            self.__context__['info'] = info
        return info
    def __getattr__(self, attr):
        info = self.__buffered_get_info__()
        if attr in info:
            return info[attr]
        else:
            raise AttributeError('No such attribute "%s"' % attr)

class LazyObject:
    def __init__(self, compute):
        self.obj = None
        self.computed = False
        self.compute = compute
    def __getattr__(self, attr):
        if self.computed is False:
            self.obj = self.compute()
            self.computed = True
        obj_attr = getattr(self.obj, attr)
        setattr(self, attr, obj_attr)   # shortcut for next call
        return obj_attr
    def __len__(self):
        return self.__getattr__('__len__')()
    def __getitem__(self, i):
        return self.__getattr__('__getitem__')(i)
    def __iter__(self):
        return self.__getattr__('__iter__')()

def APIObjectRegistryClass(d, doc=None, show_size=True):
    class APIObjectRegistryImpl(APIObjectBase):
        __doc__ = doc
        def __getitem__(self, k):
            try:
                return d[k]
            except KeyError:
                pass
            raise KeyError('Sorry, no object at key "%s"' % str(k))
        def __doc_subitems__(self):
            return d.items()
        def __iter__(self):
            return iter(d)
        def items(self):
            "Iterate over key & value pairs this set contains"
            return d.items()
        def keys(self):
            "Iterate over keys this set contains"
            return d.keys()
        def values(self):
            "Iterate over values this set contains"
            return d.values()
        def __len__(self):
            "Indicate how many items this set contains"
            return len(d)
        @property
        def __dynamic_doc__(self):
            doc =  self.__class__.__doc__
            if show_size:
                doc += ' (%d items)' % len(self)
            return doc
        def __getattr__(self, attr):
            if attr in d:
                return d[attr]
            else:
                return super().__getattr__(attr)
        def __dir__(self):
            l = super().__dir__()
            l += [ k for k in d if isinstance(k, str) ]
            return l
    return APIObjectRegistryImpl

def APIObjectRegistry(*args):
    cls = APIObjectRegistryClass(*args)
    return cls()    # instanciate
