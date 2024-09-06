from walt.client.apiobject.base import APIObjectBase
from walt.common.netsetup import NetSetup

CONFIG_GET_TRANSFORMS = {
    "netsetup": lambda int_val: NetSetup(int_val).readable_string()
}


def _get_prop(prop, config_instance):
    v = config_instance.__buffered_get_info__()[prop]
    if prop in CONFIG_GET_TRANSFORMS:
        v = CONFIG_GET_TRANSFORMS[prop](v)
    return v


def _set_prop(set_func, prop, config_instance, value):
    set_func(prop, value)


class APINodeConfig:
    def __new__(cls, get_func, set_func):
        class APINodeConfig(APIObjectBase):
            """node configuration"""

            def __init__(self):
                APIObjectBase.__init__(self)
                self._cls_init(self)

            @classmethod
            def _cls_init(cls, instance):
                import functools
                for prop in instance.__buffered_get_info__().keys():
                    setattr(
                        cls,
                        prop,
                        property(
                            functools.partial(_get_prop, prop),
                            functools.partial(_set_prop, set_func, prop)
                        ),
                    )

            def __get_remote_info__(self):
                return get_func()

        return APINodeConfig()
