import importlib, pkgutil, walt.client

def load_client_module(name):
    try:
        return importlib.import_module('walt.client.' + name)
    except ModuleNotFoundError:
        return None

def add_category(app_cls, name):
    mod = load_client_module(name)
    if mod is None:
        return False
    # module must provide an attribute "WALT_CLIENT_CATEGORY"
    category_info = getattr(mod, 'WALT_CLIENT_CATEGORY', None)
    if category_info is not None:
        app_cls.subcommand(*category_info)
        return True
    else:
        return False

def iter_client_module_names():
    for finder, name, ispkg in pkgutil.iter_modules(walt.client.__path__):
        yield name

def add_all_categories(app_cls):
    for name in iter_client_module_names():
        add_category(app_cls, name)

PLUGINS = None
def get_plugins():
    global PLUGINS
    if PLUGINS is None:
        PLUGINS = set()
        for name in iter_client_module_names():
            mod = load_client_module(name)
            plugin = getattr(mod, 'WALT_CLIENT_PLUGIN', None)
            if plugin is not None:
                PLUGINS.add(plugin)
    return PLUGINS

def get_hook(hook_name):
    for plugin in get_plugins():
        if hook_name in plugin.hooks:
            return plugin.hooks[hook_name]
