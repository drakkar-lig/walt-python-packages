from walt.client.apiobject.base import APIObjectBase
from walt.common.netsetup import NetSetup

CONFIG_GET_TRANSFORMS = {
    "netsetup": lambda int_val: NetSetup(int_val).readable_string()
}


class APINodeConfig:
    def __new__(cls, get_func, set_func):
        class APINodeConfig(APIObjectBase):
            """node configuration"""

            def _get_prop(self, prop):
                for k, v in get_func().items():
                    if k.replace(".", "_") != prop:
                        continue
                    if k in CONFIG_GET_TRANSFORMS:
                        v = CONFIG_GET_TRANSFORMS[k](v)
                    return v

            def _set_prop(self, prop, value):
                for k in get_func().keys():
                    if k.replace(".", "_") != prop:
                        continue
                    return set_func(k, value)

        # note: we have to take care with the 'prop' argument of lambda,
        # which may have changed before they are called.
        # enclosing this process in another function with the value assigned
        # as a parameter default will ensure the prop variable used in lambda
        # is the parameter of this function, different at each loop.
        for k in get_func().keys():
            prop = k.replace(".", "_")

            def assign_property(prop=prop):
                setattr(
                    APINodeConfig,
                    prop,
                    property(
                        lambda self: self._get_prop(prop),
                        lambda self, value: self._set_prop(prop, value),
                    ),
                )

            assign_property()
        return APINodeConfig()
