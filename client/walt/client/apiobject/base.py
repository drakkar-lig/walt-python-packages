ELLIPSIS = "\u2026"
MAX_SHORT_DESC_LEVEL_1 = 30


# iterate over "names" ensuring they are all different.
# if 2 names match, use a conflict pattern to modify the
# new occurence, for instance by adding a suffix "_2",
# then "_3", etc.
def iter_uniq(names, conflict_pattern):
    import itertools

    seen = set()
    for name in names:
        if name in seen:
            for i in itertools.count(start=2):
                alt_name = conflict_pattern % (name, i)
                if alt_name not in seen:
                    name = alt_name
                    break
        seen.add(name)
        yield name


def snakecase(name):
    import re

    name = re.sub("[^ a-zA-Z0-9]", " ", name)
    name = re.sub("([a-z])([A-Z])", r"\1 \2", name)  # if it was camel case
    return "_".join(w.lower() for w in name.split())


def shortcut_names(names):
    import itertools

    names, it2 = itertools.tee(names)
    attr_names = (snakecase(name) for name in it2)
    shortcuts = iter_uniq(attr_names, conflict_pattern="%s_%d")
    return zip(names, shortcuts)


class APICommentedString(str):
    def __new__(cls, s, comment):
        instance = super().__new__(cls, s)
        instance._comment = comment
        return instance

    def __repr__(self):
        return super().__repr__() + "  # " + self._comment


def short_repr(obj):
    if isinstance(obj, APIObjectBase):
        return obj.__repr__(level=1)
    elif isinstance(obj, list):
        return "[" + ", ".join(short_repr(elem) for elem in obj) + "]"
    elif isinstance(obj, Exception):
        return "<" + str(obj) + ">"
    else:
        res = repr(obj)
        if len(res) > 70:
            res = res[:67] + "..."
        return res


def get_ro_rw_props(obj):
    import inspect

    ro_props, rw_props = (), ()
    for attr_name, attr_val in inspect.getmembers(
        obj.__class__, inspect.isdatadescriptor
    ):
        if attr_name.startswith("_"):
            continue
        if attr_val.fset is not None:
            rw_props += (attr_name,)
        else:
            ro_props += (attr_name,)
    return ro_props, rw_props


def get_ro_names(obj):
    ro_attrs = tuple(k for k, v in obj.__doc_attrs__())
    ro_props, rw_props = get_ro_rw_props(obj)
    return ro_attrs + ro_props


def get_attrs_desc(obj):
    # regular attributes
    ro_attrs = {k: v for k, v in obj.__doc_attrs__()}
    rw_attrs = {}
    # properties
    ro_props, rw_props = get_ro_rw_props(obj)
    for attrs, props in ((ro_attrs, ro_props), (rw_attrs, rw_props)):
        for prop in props:
            try:
                attrs[prop] = getattr(obj, prop)
            except Exception as e:
                attrs[prop] = e
    desc = ""
    for category, attrs in (
        ("read-only attributes", ro_attrs),
        ("writable attributes", rw_attrs),
    ):
        if len(attrs) > 0:
            desc += (
                f"\n  {category}:\n"
                + "\n".join(
                    f"  - self.{k}: {short_repr(v)}" for k, v in sorted(attrs.items())
                )
                + "\n"
            )
    return tuple(ro_attrs.keys()) + tuple(rw_attrs.keys()), desc


def get_method_doc(obj, method):
    doc = getattr(method, "__doc__", None)
    if doc is None:
        if hasattr(obj, "__dynamic_method_doc__"):
            doc = obj.__dynamic_method_doc__(method)
    if doc is None:
        doc = "<undocumented>"
    return doc


def get_methods_desc(obj, excluded_attrs):
    import inspect

    # we cannot directly use inspect.getmembers(obj, inspect.ismethod)
    # because it would cause evaluation of properties, and evaluation of properties
    # may throw exceptions.
    method_names = []
    for attr in obj.__dir__():
        if attr.startswith("_") or attr in excluded_attrs:
            continue
        val = getattr(obj, attr)
        if inspect.ismethod(val):
            method_names.append(attr)
    res = ""
    if len(method_names) > 0:
        res += "\n  methods:\n"
        for method_name in sorted(method_names):
            method = getattr(obj.__class__, method_name)
            res += (
                "  - self."
                + method.__name__
                + str(inspect.signature(method))
                + ": "
                + get_method_doc(obj, method)
                + "\n"
            )
    return res


def get_preview_desc(obj):
    if hasattr(obj, "_preview"):
        return "\n  preview:\n  " + "\n  ".join(obj._preview.splitlines()) + "\n"
    else:
        return ""


def get_subitem_accessor(k):
    return "self[" + repr(k) + "]"


def get_subitems_desc(obj):
    items = sorted(obj.__doc_subitems__())
    if len(items) == 0:
        return ""
    subitems_text = "\n".join(
        f"  - {get_subitem_accessor(k)}: {short_repr(v)}" for k, v in items
    )
    return f"""
  sub-items:
{subitems_text}

  note: these sub-items are also accessible using self.<shortcut> for handy completion.
        (use <obj>.<tab><tab> to list these shortcuts)
"""


class APIObjectBase:
    def __init__(self):
        self.__context__ = None

    def __get_remote_info__(self):  # overwrite in subclass
        return {}

    def __doc_subitems__(self):  # overwrite in subclass if needed
        return ()

    def __volatile_attrs__(self):  # overwrite in subclass if needed
        return ()

    def __force_refesh__(self):  # overwrite in subclass if needed
        return

    @property
    def __dynamic_doc__(self):  # overwrite in subclass if needed
        if hasattr(self, "__doc__"):
            return self.__doc__
        else:
            return self.__class__.__doc__

    def __doc_attrs__(self):  # overwrite in subclass if needed
        if len(self.__volatile_attrs__()) > 0:
            self.__force_refresh__()
            self.__discard_context__()
        info = self.__buffered_get_info__()
        return info.items()

    def __discard_context__(self):
        if self.__context__ is not None:
            self.__context__.pop("info", None)  # discard

    def __repr_context__(self):
        from contextlib import contextmanager

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
                if len(short_desc) > MAX_SHORT_DESC_LEVEL_1:
                    short_desc = short_desc[: (MAX_SHORT_DESC_LEVEL_1 - 1)] + ELLIPSIS
                return "<" + short_desc + ">"
            elif level == 0:
                attr_names, attr_desc = get_attrs_desc(self)
                res = "< -- " + short_desc + " --\n"
                res += attr_desc
                res += get_methods_desc(self, excluded_attrs=attr_names)
                res += get_subitems_desc(self)
                res += get_preview_desc(self)
                res += ">"
            return res

    def __buffered_get_info__(self):
        # it's expensive to request several times info() on remote object,
        # so if we have a running context, save it there
        if self.__context__ is not None:
            if "info" in self.__context__:
                return self.__context__["info"]
        info = self.__get_remote_info__()
        if self.__context__ is not None:
            self.__context__["info"] = info
        return info

    def __getattr__(self, attr):
        if attr in self.__volatile_attrs__():
            self.__force_refresh__()
            self.__discard_context__()
        info = self.__buffered_get_info__()
        if attr in info:
            return info[attr]
        else:
            raise AttributeError('No such attribute "%s"' % attr)

    def __setattr__(self, attr, value):
        if attr.startswith("_"):
            return super().__setattr__(attr, value)
        ro_names = get_ro_names(self)
        if attr in ro_names:
            raise AttributeError('Cannot write read-only attribute "%s"' % attr)
        else:
            return super().__setattr__(attr, value)

    def __dir__(self):
        attrs = super().__dir__()
        attrs += list(self.__buffered_get_info__().keys())
        return attrs


def api_namedtuple_cls(cls_name, keys):
    from collections import namedtuple

    keys = list(keys)
    nt_cls = namedtuple(cls_name, keys)

    def repr_nt(nt):
        attrs_line = ", ".join(f"{k}={short_repr(v)}" for k, v in nt._asdict().items())
        return f"{cls_name}({attrs_line})"

    nt_cls.__repr__ = repr_nt
    return nt_cls


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
        setattr(self, attr, obj_attr)  # shortcut for next call
        return obj_attr

    def __len__(self):
        return self.__getattr__("__len__")()

    def __getitem__(self, i):
        return self.__getattr__("__getitem__")(i)

    def __iter__(self):
        return self.__getattr__("__iter__")()


class APIFilteredSet:
    def __init__(self, object_cache, object_factory_cls, names):
        assert isinstance(
            names, set
        ), "APIFilteredSet must be built with a set of names."
        self._names = names
        self._object_cache = object_cache
        self._object_cache.register_obj(self)
        self._object_factory_cls = object_factory_cls

    def __getitem__(self, k):
        if k not in self._names:
            raise KeyError('Sorry, no object at key "%s"' % str(k))
        return self._object_factory_cls.create(k)

    def __iter__(self):
        return iter(self._names)

    def items(self):
        return iter((k, self[k]) for k in self._names)

    def names(self):
        return iter(self._names)

    def values(self):
        return iter(self[k] for k in self._names)

    def __len__(self):
        return len(self._names)

    def add(self, k):
        self._names.add(k)

    def get(self, k, default=None):
        if k in self._names:
            return self[k]
        else:
            return default

    def __delitem__(self, k):
        del self._object_cache[k]

    def __propagate_delitem__(self, k):
        if k in self._names:
            self._names.remove(k)

    def rename(self, k, k2):
        self._object_cache.rename(k, k2)

    def __propagate_rename__(self, k, k2):
        if k in self._names:
            self._names.remove(k)
            self._names.add(k2)


def APIObjectRegistryClass(d, doc=None, show_size=True):
    class APIObjectRegistryImpl(APIObjectBase):
        __doc__ = doc
        __methods_doc__ = {}

        def __getitem__(self, k):
            try:
                return d[k]
            except KeyError:
                pass
            raise KeyError('Sorry, no object at key "%s"' % str(k))

        def __doc_subitems__(self):
            return d.items()

        def __iter__(self):
            return iter(d.values())

        def __contains__(self, k):
            return k in d.names() or k in d.values()

        def items(self):
            "Iterate over key & value pairs this set contains"
            return d.items()

        def keys(self):
            "Iterate over keys this set contains"
            return d.names()

        def values(self):
            "Iterate over values this set contains"
            return d.values()

        def __len__(self):
            "Indicate how many items this set contains"
            return len(d)

        def get(self, k, default=None):
            "Return item specified or default value if missing"
            return d.get(k, default)

        @property
        def __dynamic_doc__(self):
            doc = super().__dynamic_doc__
            if show_size:
                doc += " (%d items)" % len(self)
            return doc

        def __shortcut_names__(self):
            items = sorted(self.__doc_subitems__())
            return shortcut_names(item[0] for item in items)

        def __getattr__(self, attr):
            # attr may be a shortcut for a subitem of d
            for k, shortcut in self.__shortcut_names__():
                if shortcut == attr:
                    return d[k]
            # otherwise, it may be a regular attribute
            return super().__getattr__(attr)

        def __dir__(self):
            attrs = super().__dir__()
            attrs += [shortcut for k, shortcut in self.__shortcut_names__()]
            return attrs

    return APIObjectRegistryImpl


def APIObjectRegistry(*args):
    cls = APIObjectRegistryClass(*args)
    return cls()  # instanciate


class APIItemClassFactory:
    @staticmethod
    def create(
        object_cache, in_item_name, item_cls_label, item_base_cls, item_set_factory
    ):
        class APIItem(APIObjectBase):
            _item_name = in_item_name  # class attribute

            @classmethod
            def __check_deleted__(cls):
                if cls._item_name not in object_cache:
                    raise ReferenceError("This item is no longer valid! (was removed)")

            @property
            def __dynamic_doc__(self):
                return f"{item_cls_label} {self.__class__._item_name}"

            def __dynamic_method_doc__(self, method):
                return f"""{method.__name__.capitalize()} this {item_cls_label}"""

            def __get_remote_info__(self):
                self.__class__.__check_deleted__()
                return object_cache[self.__class__._item_name].copy()

            @property
            def name(self):
                return self.__class__._item_name

            def __remove_from_cache__(self):
                del object_cache[self.__class__._item_name]

            def __propagate_delitem__(self, k):
                pass

            def __rename_in_cache__(self, new_name):
                object_cache.rename(self.__class__._item_name, new_name)

            def __propagate_rename__(self, k, k2):
                if self.__class__._item_name == k:
                    self.__class__._item_name = k2

            def __or__(self, other):
                if isinstance(other, item_base_cls):
                    return item_set_factory.create(
                        {self.__class__._item_name, other._item_name}
                    )
                return NotImplemented

            def __eq__(self, other):
                if not isinstance(other, item_base_cls):
                    return False
                return other.name == self.name

            def __hash__(self):
                return hash(self.name)

        return APIItem


class APISetOfItemsClassFactory:
    @staticmethod
    def create(
        object_cache,
        in_names,
        item_cls_label,
        item_base_cls,
        item_factory,
        item_set_base_cls,
        item_set_factory,
    ):
        in_names = set(in_names)
        d = APIFilteredSet(object_cache, item_factory, in_names)

        class APISetOfItems(APIObjectRegistryClass(d)):
            _names = in_names

            def __dynamic_method_doc__(self, method):
                if method.__name__ == "filter":
                    return (f"Return the subset of {item_cls_label}s"
                            " matching the given attributes")

            def filter(self, **kwargs):
                new_set = item_set_factory.create(set())
                for item in d.values():
                    item_ok = True
                    for k, v in kwargs.items():
                        if getattr(item, k) != v:
                            item_ok = False
                            break
                    if item_ok:
                        new_set |= item
                return new_set

            def __ior__(self, other):
                if isinstance(other, item_base_cls):
                    # add an item
                    self.__class__._names |= {other.name}
                    return self
                if isinstance(other, item_set_base_cls):
                    # add items of another set
                    self.__class__._names |= other._names
                    return self
                return NotImplemented

            def __or__(self, other):
                new_set = item_set_factory.create(self.__class__._names.copy())
                new_set |= other  # call __ior__ above
                return new_set

            def __iand__(self, other):
                if isinstance(other, item_set_base_cls):
                    # intersect with another set
                    self.__class__._names &= other._names
                    return self
                return NotImplemented

            def __and__(self, other):
                new_set = item_set_factory.create(self.__class__._names.copy())
                new_set &= other  # call __iand__ above
                return new_set

        return APISetOfItems


class APIItemInfoCache:
    def __init__(self, show_aliases=False):
        self.listeners_refs = set()
        self.populated = False
        self.show_aliases = show_aliases

    def server_link(self):
        from walt.client.apitools import silent_server_link

        return silent_server_link()

    def ensure_populated(self):
        if not self.populated:
            self.refresh()
            self.populated = True

    def refresh(self):
        with self.server_link() as server:
            self.do_refresh(server)

    def __contains__(self, item_name):
        self.ensure_populated()
        return item_name in self.id_per_name

    def __getitem__(self, item_name):
        self.ensure_populated()
        item_id = self.id_per_name[item_name]
        info = self.info_per_id[item_id]
        if self.show_aliases:
            info.update(aliases=self.names_per_id[item_id])
        return info

    def __delitem__(self, item_name):
        self.ensure_populated()
        with self.server_link() as server:
            if not self.do_remove_item(server, item_name):
                return  # failed
        item_id = self.id_per_name[item_name]
        self.names_per_id[item_id].remove(item_name)
        if len(self.names_per_id[item_id]) == 0:
            del self.names_per_id[item_id]
            del self.info_per_id[item_id]
        del self.id_per_name[item_name]
        for obj in self.valid_listeners():
            obj.__propagate_delitem__(item_name)

    def names(self):
        self.ensure_populated()
        return self.id_per_name.keys()

    def register_obj(self, obj):
        import weakref

        self.listeners_refs.add(weakref.ref(obj))

    def valid_listeners(self):
        checked_refs = set()
        checked_listeners = set()
        for ref in self.listeners_refs:
            obj = ref()
            if obj is None:
                continue
            checked_refs.add(ref)
            checked_listeners.add(obj)
        self.listeners_refs = checked_refs
        return checked_listeners

    def rename(self, item_name, new_item_name):
        self.ensure_populated()
        with self.server_link() as server:
            if not self.do_rename_item(server, item_name, new_item_name):
                return  # failed
        item_id = self.id_per_name[item_name]
        self.names_per_id[item_id].remove(item_name)
        self.names_per_id[item_id].add(new_item_name)
        del self.id_per_name[item_name]
        self.id_per_name[new_item_name] = item_id
        for obj in self.valid_listeners():
            obj.__propagate_rename__(item_name, new_item_name)

    def do_refresh(self, server):
        raise NotImplementedError  # should be implemented in sub-class

    def do_remove_item(self, server, item_name):
        raise NotImplementedError  # should be implemented in sub-class

    def do_rename_item(self, server, item_name, new_item_name):
        raise NotImplementedError  # should be implemented in sub-class
