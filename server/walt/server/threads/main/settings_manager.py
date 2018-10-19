# Handlers are generators.  They are created with their parameters, which are
# always the requester, the device_set and the setting_value.  Then, their code
# are divided in two parts: firstly, they check all conditions to ensure the
# setting is coherent, valid, available for the devices, etc.  They yield a
# boolean to indicate if the tests have succeed or not.  The second part (after
# the yield) effectively configure the setting on the devices.  The caller may
# ask for checks (the first part) and not for action (the second).  The caller
# must not ask for the action if the checks failed (yielded False).


class SettingsHandler:
    def __init__(self, server):
        self.server = server

    def set_device_config(self, requester, device_set, settings_args):
        # Parse the settings
        if len(settings_args) % 2 != 0:
            requester.stderr.write(
                "Provide settings as `<setting name> <setting value>` pairs.\n")
            return
        configurations = list(zip(settings_args[::2], settings_args[1::2]))

        # ensure all settings are known and retrieve their respective handlers
        handlers = []
        for setting_name, setting_value in configurations:
            try:
                handler_name = setting_name + "_setting_handler"
                handler = getattr(self, handler_name)
            except AttributeError:
                requester.stderr.write(
                    "Unknown setting '%s'.\n" % setting_name)
                return
            handlers.append(handler(  # no code of the handler is run there, as it is a generator
                requester, device_set, setting_value))

        # first part: ensure all settings are ok for the devices
        for handler in handlers:
            # run the first part of the handler function: the sanity checks
            checks_passed = next(handler)
            if not checks_passed:
                return

        # second part: effectively configure the devices
        for handler in handlers:
            try:
                # run the second part of the handler function: the effective action
                next(handler)
                # ERROR: the handler has not finished its job!
            except StopIteration:
                # OK, the handler has finished its job
                pass

    def netsetup_setting_handler(self, requester, device_set, setting_value):
        return self.server.nodes.netsetup_handler(requester, device_set, setting_value)
