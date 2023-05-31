# category added to walt command line tool
CATEGORIES = [
    ("g5k", "g5k.cli", "WalTG5K"),
]

# name to use when running pip install walt-client[<name>]
PLUGIN_FEATURE_NAME = "g5k"

# hook methods
PLUGIN_HOOKS = {
    "config_missing_server": "walt.client.g5k.plugin.config_missing_server_hook",
    "failing_server_socket": "walt.client.g5k.plugin.failing_server_socket_hook",
    "client_hard_reboot": "walt.client.g5k.reboot.G5KClientHardRebootHook",
    "shell_completion_hook": "walt.client.g5k.autocomplete.shell_completion_hook",
    "early_startup": "walt.client.g5k.startup.early_startup",
}
