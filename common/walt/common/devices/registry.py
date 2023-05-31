PROBE_FUNCTIONS = None


def get_device_info_from_mac(mac):
    if PROBE_FUNCTIONS is None:
        register_all_probe_functions()
    for probe in PROBE_FUNCTIONS:
        info = probe(mac)
        if info is not None:
            return info
    return {}  # no information found


def register_all_probe_functions():
    global PROBE_FUNCTIONS
    import inspect

    from walt.common.devices import switches

    all_modules = []
    # add all modules in 'switches' subdir
    for package in (switches,):
        all_modules.extend(
            module for name, module in inspect.getmembers(package, inspect.ismodule)
        )
    PROBE_FUNCTIONS = [module.probe for module in all_modules]
