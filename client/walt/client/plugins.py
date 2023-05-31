import importlib
import pkgutil

import walt.client.metadata


def load_module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


def iter_sub_modules(parent):
    for finder, name, ispkg in pkgutil.iter_modules(parent.__path__):
        yield load_module(f"{parent.__name__}.{name}")


METADATA = None


def load_plugins_metadata():
    global METADATA
    if METADATA is not None:
        return  # already loaded
    METADATA = dict(
        categories={},
        feature_names=[],
        hooks={},
    )
    for mod in iter_sub_modules(walt.client.metadata):
        categories = getattr(mod, "CATEGORIES", None)
        if categories is not None:
            METADATA["categories"].update(
                {name: (modname, objname) for name, modname, objname in categories}
            )
        feature_name = getattr(mod, "PLUGIN_FEATURE_NAME", None)
        if feature_name is not None:
            METADATA["feature_names"] += [feature_name]
        hooks = getattr(mod, "PLUGIN_HOOKS", None)
        if hooks is not None:
            METADATA["hooks"].update(hooks)


def get_plugin_feature_names():
    load_plugins_metadata()
    return METADATA["feature_names"]


def get_hook(hook_name):
    load_plugins_metadata()
    hook_path = METADATA["hooks"].get(hook_name, None)
    if hook_path is None:
        return None
    hook_modpath, hook_varname = hook_path.rsplit(".", maxsplit=1)
    mod = load_module(hook_modpath)
    return getattr(mod, hook_varname)


def run_hook_if_any(hook_name, *args, **kwargs):
    hook = get_hook(hook_name)
    if hook is not None:
        return hook(*args, **kwargs)


def add_category(app_cls, name):
    load_plugins_metadata()
    if name not in METADATA["categories"]:
        return False
    modname, objname = METADATA["categories"][name]
    mod = load_module(f"walt.client.{modname}")
    category_obj = getattr(mod, objname)
    app_cls.subcommand(name, category_obj)


def add_all_categories(app_cls):
    load_plugins_metadata()
    for name in METADATA["categories"]:
        add_category(app_cls, name)
    return True
