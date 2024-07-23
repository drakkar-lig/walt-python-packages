import json
import re
from collections import defaultdict

from walt.common.formatting import format_sentence
from walt.common.netsetup import NetSetup
from walt.common.settings import parse_vnode_disks_value, parse_vnode_networks_value
from walt.common.tools import do
from walt.server.processes.main.network import tftp
from walt.server.processes.main.nodes.manager import (
    VNODE_DEFAULT_CPU_CORES,
    VNODE_DEFAULT_DISKS,
    VNODE_DEFAULT_NETWORKS,
    VNODE_DEFAULT_RAM,
    VNODE_DEFAULT_BOOT_DELAY,
    NODE_DEFAULT_BOOT_RETRIES,
    NODE_DEFAULT_BOOT_TIMEOUT,
    NODE_MIN_BOOT_TIMEOUT,
)
from walt.server.tools import ip_in_walt_network, np_record_to_dict

PPRINT_NONE = "<unspecified>"


def uncapitalize(s):
    return s[0].lower() + s[1:]


def pprint_netsetup(int_val):
    if int_val is None:
        return PPRINT_NONE
    else:
        return NetSetup(int_val).readable_string()


def pprint_bool(bool_val):
    if bool_val is None:
        return PPRINT_NONE
    else:
        return str(bool_val).lower()


def parse_settings_args(requester, settings_args):
    all_settings = {}
    for arg in settings_args:
        parts = arg.split("=", maxsplit=1)
        if len(parts) != 2:
            requester.stderr.write(
                "Please provide settings as `<setting name>=<setting value>` arguments.\n"
            )
            return None
        all_settings[parts[0]] = parts[1]
    return all_settings


def positive_int(s):
    try:
        i = int(s)
        if i >= 0:
            return True
    except ValueError:
        pass
    return False


class SettingsManager:
    def __init__(self, server):
        self.server = server
        self.settings_table = {
            "netsetup": {
                "category": "walt-net-devices",
                "value-check": self.correct_netsetup_value,
                "default": int(NetSetup.LAN),
                "pretty_print": pprint_netsetup,
            },
            "ram": {
                "category": "virtual-nodes",
                "value-check": self.correct_ram_value,
                "default": VNODE_DEFAULT_RAM,
            },
            "cpu.cores": {
                "category": "virtual-nodes",
                "value-check": self.correct_cpu_value,
                "default": VNODE_DEFAULT_CPU_CORES,
            },
            "disks": {
                "category": "virtual-nodes",
                "value-check": self.correct_disks_value,
                "default": VNODE_DEFAULT_DISKS,
            },
            "boot.delay": {
                "category": "virtual-nodes",
                "value-check": self.correct_boot_delay,
                "default": VNODE_DEFAULT_BOOT_DELAY,
            },
            "boot.retries": {
                "category": "nodes",
                "value-check": self.correct_boot_retries,
                "default": NODE_DEFAULT_BOOT_RETRIES,
            },
            "boot.timeout": {
                "category": "nodes",
                "value-check": self.correct_boot_timeout,
                "default": NODE_DEFAULT_BOOT_TIMEOUT,
                "pretty_print": lambda s: ("none" if s is None else str(s)),
            },
            "networks": {
                "category": "virtual-nodes",
                "value-check": self.correct_networks_value,
                "default": VNODE_DEFAULT_NETWORKS,
            },
            "type": {
                "category": "unknown-devices",
                "value-check": self.value_is_switch,
                "default": "unknown",
            },
            "lldp.explore": {
                "category": "switches",
                "value-check": self.correct_lldp_explore_value,
                "default": False,
                "pretty_print": pprint_bool,
            },
            "poe.reboots": {
                "category": "switches",
                "value-check": self.correct_poe_reboots_value,
                "default": False,
                "pretty_print": pprint_bool,
            },
            "snmp.version": {
                "category": "switches",
                "value-check": self.correct_snmp_version_value,
                "default": None,
            },
            "snmp.community": {
                "category": "switches",
                "value-check": self.correct_snmp_community_value,
                "default": None,
            },
            "kexec.allow": {
                "category": "nodes",
                "value-check": self.correct_kexec_allow_value,
                "default": True,
                "pretty_print": pprint_bool,
            },
            "mount.persist": {
                "category": "nodes",
                "value-check": self.correct_mount_persist_value,
                "default": True,
                "pretty_print": pprint_bool,
            },
            "expose": {
                "category": "walt-net-devices",
                "value-check": self.correct_expose_value,
                "default": "none",
            },
        }
        self.category_filters = {
            "devices": self.filter_devices,
            "server": self.filter_server,
            "walt-net-devices": self.filter_walt_net_devices,
            "nodes": self.filter_nodes,
            "virtual-nodes": self.filter_virtual_nodes,
            "unknown-devices": self.filter_unknown_devices,
            "switches": self.filter_switches,
        }
        self.category_labels = {
            "devices": dict(priority=1, labels=("Device", "Devices")),
            "server": dict(priority=3, labels=("Server", None)),
            "walt-net-devices": dict(priority=2, labels=("Device", "Devices")),
            "nodes": dict(priority=3, labels=("Node", "Nodes")),
            "virtual-nodes": dict(priority=4, labels=("Virtual node", "Virtual nodes")),
            "unknown-devices": dict(
                priority=3, labels=("Unknown device", "Unknown devices")
            ),
            "switches": dict(priority=3, labels=("Switch", "Switches")),
        }

    def correct_kexec_allow_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        return self.correct_bool_value(requester, setting_name, setting_value)

    def correct_mount_persist_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        return self.correct_bool_value(requester, setting_name, setting_value)

    def correct_snmp_community_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        return True

    def correct_snmp_version_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if setting_value not in ("1", "2"):
            requester.stderr.write(
                "Failed: value of setting 'snmp.version' should be '1' or '2'.\n"
            )
            return False
        return True

    def correct_bool_value(self, requester, setting_name, setting_value):
        if setting_value.lower() not in ("true", "false"):
            requester.stderr.write(
                "Failed: setting '%s' only allows values 'true' or 'false'.\n"
                % setting_name
            )
            return False
        return True

    def correct_poe_reboots_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if not self.correct_bool_value(requester, setting_name, setting_value):
            return False
        if setting_value.lower() == "true":
            # check that lldp.explore is also true, because for a PoE reboot we need to
            # know where the node is connected.
            lldp_explore = all_settings.get("lldp.explore")
            if lldp_explore is not None:
                if lldp_explore.lower() == "true":
                    return True  # OK
                if lldp_explore.lower() == "false":
                    requester.stderr.write(
                        "Failed: cannot set 'poe.reboots' to true unless 'lldp.explore'"
                        " is set to true too.\n"
                    )
                    return False
            else:
                # lldp.explore was not specified on this command line,
                # look for it in existing configuration of all requested devices
                for device_info in device_infos:
                    lldp_explore = device_info.conf.get("lldp.explore")
                    if lldp_explore is None or lldp_explore is False:
                        requester.stderr.write(
                            "Failed: cannot set 'poe.reboots' to true unless"
                            " 'lldp.explore' is set to true too.\n"
                        )
                        return False
        return True

    def correct_lldp_explore_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if not self.correct_bool_value(requester, setting_name, setting_value):
            return False
        if setting_value.lower() == "true":
            # check that snmp conf is provided by other settings or was
            # configured previously
            version_ok = "snmp.version" in all_settings
            community_ok = "snmp.community" in all_settings
            if version_ok and community_ok:
                return True
            # check if these settings were already set previously (whether we can find
            # them in existing conf of all requested devices).
            for device_info in device_infos:
                all_fine = True
                if version_ok is False:
                    all_fine = device_info.conf.get("snmp.version") is not None
                if community_ok is False:
                    all_fine = device_info.conf.get("snmp.community") is not None
                if not all_fine:
                    requester.stderr.write(
                        "Failed: cannot set 'lldp.explore' to true unless"
                        " 'snmp.version' and 'snmp.community' are defined too.\n"
                    )
                    return False
        return True

    def value_is_switch(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if setting_value != "switch":
            requester.stderr.write(
                "Failed: setting '%s' only allows value 'switch'.\n" % setting_name
            )
            return False
        return True

    def correct_cpu_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if positive_int(setting_value):
            return True
        requester.stderr.write(
            "Failed: '%s' is not a valid value for cpu.cores (expecting for"
            " instance 1 or 4).\n" % setting_value
        )
        return False

    def correct_ram_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if re.match(r"^\d+[MG]$", setting_value) is None:
            requester.stderr.write(
                "Failed: '%s' is not a valid value for ram (expecting for instance 512M"
                " or 1G).\n" % setting_value
            )
            return False
        return True

    def correct_disks_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        parsing = parse_vnode_disks_value(setting_value)
        if parsing[0] is False:
            error = parsing[1]
            requester.stderr.write(
                f"Failed: {error}\n"
                + "        Check 'walt help show device-config' for more info.\n"
            )
            return False
        return True

    def correct_boot_delay(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if (setting_value == 'random'):
            return True
        if positive_int(setting_value):
            return True
        requester.stderr.write(
            f"Failed: '{setting_value}' is not a valid value for option 'boot.delay'.\n"
            "        Use for example '2' for 2s, '0' to disable, "
            "'random' for a random delay between 1 and 10s.\n"
        )
        return False

    def correct_boot_retries(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if positive_int(setting_value):
            return True
        requester.stderr.write(
            f"Failed: '{setting_value}' is not a valid value for option "
            "'boot.retries'.\n"
            "        Use for example '2' for retrying twice after a failed boot, "
            "'0' to disable.\n"
        )
        return False

    def correct_boot_timeout(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if setting_value == "none":
            return True
        if not positive_int(setting_value):
            requester.stderr.write(
                f"Failed: '{setting_value}' is not a valid value for option "
                "'boot.timeout'.\n"
                "        Use for example '180' for waiting 3 minutes before "
                "considering the node is stuck and force-rebooting it, "
                "or 'none' to disable.\n"
            )
            return False
        if int(setting_value) < NODE_MIN_BOOT_TIMEOUT:
            requester.stderr.write(
                f"Failed: A boot timeout of {setting_value}s is probably too small "
                "for some OS images.\n"
                f"        Only \"none\" and values higher than {NODE_MIN_BOOT_TIMEOUT}"
                " are allowed for this setting.\n"
            )
            return False
        return True

    def correct_networks_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        parsing = parse_vnode_networks_value(setting_value)
        if parsing[0] is False:
            error = parsing[1]
            requester.stderr.write(
                f"Failed: {error}\n"
                + "        Check 'walt help show device-config' for more info.\n"
            )
            return False
        return True

    def correct_netsetup_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        try:
            NetSetup(setting_value)
            return True
        except ValueError:
            requester.stderr.write("Failed: netsetup value should be 'NAT' or 'LAN'.\n")
            return False

    def correct_expose_value(
        self, requester, device_infos, setting_name, setting_value, all_settings
    ):
        if len(device_infos) > 1:
            requester.stderr.write(
                  "Failed: cannot expose the same server port for several devices.\n")
            return False
        return self.server.expose.check_expose_setting_value(
                    requester, device_infos[0].ip, setting_value)

    def simple_filter(self, device_infos, func, ok_as_names=True, not_ok_as_names=True):
        ok, not_ok = [], []
        for di in device_infos:
            if func(di):
                ok.append(di.name if ok_as_names else di)
            else:
                not_ok.append(di.name if not_ok_as_names else di)
        return ok, not_ok

    def all_ok_filter(self, device_infos, **kwargs):
        return self.simple_filter(device_infos, lambda di: True, **kwargs)

    def filter_devices(self, requester, device_infos, setting_name):
        return self.all_ok_filter(device_infos)

    def filter_server(self, requester, device_infos, setting_name):
        dev_server, dev_other = self.simple_filter(
            device_infos, lambda di: di.type == "server"
        )
        if len(dev_other) > 0 and requester is not None:
            msg = format_sentence(
                "Failed: %s is(are) not a() WALT server(servers),"
                f" so '{setting_name}' setting cannot be applied.\n",
                dev_other,
                None,
                "Device",
                "Devices",
            )
            requester.stderr.write(msg)
        return dev_server, dev_other

    def filter_unknown_devices(self, requester, device_infos, setting_name):
        unknown, not_unknown = self.simple_filter(
            device_infos, lambda di: di.type == "unknown"
        )
        if len(not_unknown) > 0 and requester is not None:
            requester.stderr.write(
                "Failed: setting '"
                + setting_name
                + "' can only be applied to unknown devices.\n"
            )
        return unknown, not_unknown

    def filter_walt_net_devices(self, requester, device_infos, setting_name):
        dev_server, dev_other = self.simple_filter(
            device_infos,
            lambda di: di.type == "server",
            ok_as_names=True,
            not_ok_as_names=False,
        )
        dev_ok, not_in_walt_net = self.simple_filter(
            dev_other, lambda di: ip_in_walt_network(di.ip)
        )
        if requester is not None:
            reasons = []
            if len(not_in_walt_net) > 0:
                reasons.append(
                    format_sentence(
                        "%s is(are) not a() device(devices) managed inside walt-net",
                        not_in_walt_net,
                        None,
                        "device",
                        "devices",
                    )
                )
            if len(dev_server) > 0:
                reasons.append("%s is the WALT server" % dev_server[0])
            if len(reasons) > 0:
                msg = "Failed: " + ", and ".join(reasons) + ".\n"
                requester.stderr.write(msg)
        return dev_ok, dev_server + not_in_walt_net

    def filter_switches(self, requester, device_infos, setting_name):
        switches, not_switches = self.simple_filter(
            device_infos, lambda di: di.type == "switch"
        )
        if len(not_switches) > 0 and requester is not None:
            msg = format_sentence(
                "Failed: %s is(are) not a() switch(switches),"
                f" so '{setting_name}' setting cannot be applied.\n",
                not_switches,
                None,
                "Device",
                "Devices",
            )
            requester.stderr.write(msg)
        return switches, not_switches

    def filter_nodes(self, requester, device_infos, setting_name):
        nodes, not_nodes = self.simple_filter(
            device_infos, lambda di: di.type == "node"
        )
        if len(not_nodes) > 0 and requester is not None:
            msg = format_sentence(
                "Failed: %s is(are) not a() node(nodes), "
                "so it(they) does(do) not support the '"
                + setting_name
                + "' setting.\n",
                not_nodes,
                None,
                "Device",
                "Devices",
            )
            requester.stderr.write(msg)
        return nodes, not_nodes

    def filter_virtual_nodes(self, requester, device_infos, setting_name):
        nodes, not_nodes = self.simple_filter(
            device_infos,
            lambda di: di.type == "node",
            ok_as_names=False,
            not_ok_as_names=True,
        )
        nodes_ok, not_virtual_nodes = self.simple_filter(nodes, lambda di: di.virtual)
        if requester is not None:
            reasons = []
            if len(not_nodes) > 0:
                reasons.append(
                    format_sentence(
                        "%s is(are) not a() node(nodes)",
                        not_nodes,
                        None,
                        "device",
                        "devices",
                    )
                )
            if len(not_virtual_nodes) > 0:
                reasons.append(
                    format_sentence(
                        "%s is(are) not virtual",
                        not_virtual_nodes,
                        None,
                        "node",
                        "nodes",
                    )
                )
            if len(reasons) > 0:
                for i in tuple(range(1, len(reasons))):
                    reasons[i] = uncapitalize(reasons[i])
                msg = (
                    "Failed: "
                    + ", and ".join(reasons)
                    + f", so '{setting_name}' setting is not supported.\n"
                )
                requester.stderr.write(msg)
        return nodes_ok, not_nodes + not_virtual_nodes

    def update_vnodes_vm_setting(self, device_infos, setting_name, setting_value):
        for device_info in device_infos:
            self.server.nodes.vnode_update_vm_setting(
                   device_info.mac, setting_name, setting_value)

    def set_device_config(self, requester, device_set, settings_args):
        # parse settings
        all_settings = parse_settings_args(requester, settings_args)
        if all_settings is None:
            return

        # ensure the device set is correct
        device_infos = self.server.devices.parse_device_set(requester, device_set)
        if device_infos is None:
            return  # issue already reported

        # ensure all settings are known and pass related checks
        converting_to_switches = all_settings.get("type") == "switch"
        for setting_name, setting_value in all_settings.items():
            # check the setting is known
            setting_info = self.settings_table.get(setting_name)
            if setting_info is None:
                requester.stderr.write(
                    "Unknown setting '%s'. See: 'walt help show device-config'\n"
                    % setting_name
                )
                return

            # verify this setting pass all checks
            category = setting_info["category"]
            if category == "switches" and converting_to_switches:
                # converting_to_switches means we also have a type=switch setting in the
                # command line. thus we are actually expecting unknown devices, but this
                # will be verified by the category check of the "type[=switch]" setting.
                dev_ok, dev_not_ok = self.all_ok_filter(device_infos)  # ok for us
            else:
                category_filter = self.category_filters[category]
                dev_ok, dev_not_ok = category_filter(
                    requester, device_infos, setting_name
                )
            if len(dev_not_ok) > 0:
                return
            value_check = setting_info["value-check"]
            if not value_check(
                requester, device_infos, setting_name, setting_value, all_settings
            ):
                return

        # effectively configure the devices
        should_reboot_devices = False
        should_update_tftp = False
        db_settings = all_settings.copy()
        for setting_name, setting_value in all_settings.items():
            if setting_name == "netsetup":
                new_netsetup_state = NetSetup(setting_value)
                for device_info in device_infos:
                    if device_info.conf.get("netsetup", 0) == new_netsetup_state:
                        # skip this node: already configured
                        continue
                    # update iptables
                    do(
                        "iptables %(action)s WALT --source '%(ip)s' --jump ACCEPT"
                        % dict(
                            ip=device_info.ip,
                            action=(
                                "--insert"
                                if new_netsetup_state == NetSetup.NAT
                                else "--delete"
                            ),
                        )
                    )
                db_settings["netsetup"] = int(new_netsetup_state)
                should_reboot_devices = True
            elif setting_name == "cpu.cores":
                db_settings["cpu.cores"] = int(setting_value)
                self.update_vnodes_vm_setting(device_infos, "cpu_cores", setting_value)
                should_reboot_devices = True
            elif setting_name == "ram":
                self.update_vnodes_vm_setting(device_infos, "ram", setting_value)
                should_reboot_devices = True
            elif setting_name == "disks":
                self.update_vnodes_vm_setting(device_infos, "disks", setting_value)
                should_reboot_devices = True
            elif setting_name == "boot.delay":
                self.update_vnodes_vm_setting(device_infos, "boot_delay", setting_value)
                should_reboot_devices = True
            elif setting_name == "boot.retries":
                retries = int(setting_value)
                db_settings["boot.retries"] = retries
                for node_info in device_infos:
                    self.server.nodes.update_node_boot_retries(node_info.mac, retries)
            elif setting_name == "boot.timeout":
                timeout = setting_value
                if timeout == "none":
                    timeout = None
                else:
                    timeout = int(timeout)
                db_settings["boot.timeout"] = timeout
                for node_info in device_infos:
                    self.server.nodes.update_node_boot_timeout(node_info.mac, timeout)
            elif setting_name == "networks":
                self.update_vnodes_vm_setting(device_infos, "networks", setting_value)
                should_reboot_devices = True
            elif setting_name in ("lldp.explore", "poe.reboots", "kexec.allow"):
                # convert value to boolean
                setting_value = setting_value.lower() == "true"
                db_settings[setting_name] = setting_value
            elif setting_name == "mount.persist":
                # convert value to boolean
                setting_value = setting_value.lower() == "true"
                db_settings[setting_name] = setting_value
                should_reboot_devices = True
                should_update_tftp = True
            elif setting_name == "snmp.version":
                db_settings[setting_name] = int(setting_value)
            elif setting_name == "snmp.community":
                pass  # update in DB (below) is enough
            elif setting_name == "type":
                for device_info in device_infos:
                    device_info = np_record_to_dict(device_info)
                    device_info.update(type=setting_value)
                    self.server.devices.add_or_update(
                        requester=requester, **device_info
                    )
                # 'type' is a column of table 'devices', so this setting should not
                # be recorded in 'devices.conf' column
                del db_settings["type"]
            elif setting_name == "expose":
                for device_info in device_infos:
                    self.server.expose.apply(
                            requester, device_info.ip, setting_value)

        # save in db
        new_vals = json.dumps(db_settings)
        for di in device_infos:
            self.server.db.execute(
                "update devices set conf = conf || %s::jsonb where mac = %s",
                (new_vals, di.mac),
            )
        self.server.db.commit()

        # update tftp links if needed
        if should_update_tftp:
            tftp.update(self.server.db, self.server.images.store)

        # notify user
        if should_reboot_devices:
            label = "node(s)"
            for device_info in device_infos:
                if device_info.type != "node":
                    label = "device(s)"
                    break
            requester.stdout.write(
                f"Done. Reboot {label} to see new settings in effect.\n"
            )
        else:
            requester.stdout.write("Done.\n")

    def get_device_config_data(self, requester, device_set):
        result = {}
        # ensure the device set is correct
        device_infos = self.server.devices.parse_device_set(requester, device_set)
        if device_infos is None:
            return  # issue already reported
        # we will compute 'names_per_category' and 'main_category_per_name' variables
        # to ease the latter, we loop over categories in increasing order of priority.
        names_per_category = {}
        main_category_per_name = {}
        ordered_categories = sorted(
            self.category_labels, key=lambda k: self.category_labels[k]["priority"]
        )
        for category in ordered_categories:
            category_filter = self.category_filters[category]
            names, _ = category_filter(None, device_infos, None)
            names_per_category[category] = set(names)
            for name in names:
                main_category_per_name[name] = category
        # retrieve device settings and default values for missing ones
        for device_info in device_infos:
            dev_name = device_info.name
            # retrieve device settings
            settings = dict(device_info.conf)
            # add default value of unspecified settings
            for setting_name, setting_info in self.settings_table.items():
                category = setting_info["category"]
                if (
                    dev_name in names_per_category[category]
                    and setting_name not in settings
                ):
                    settings[setting_name] = setting_info["default"]
            result[dev_name] = {
                "category": main_category_per_name[dev_name],
                "settings": settings,
            }
        return result

    def get_device_config(self, requester, device_set):
        config_data = self.get_device_config_data(requester, device_set)
        if config_data is None:
            return  # issue already reported
        configs = defaultdict(lambda: defaultdict(list))
        for device_name, device_conf in config_data.items():
            category = device_conf["category"]
            settings = device_conf["settings"]
            # append to the list of devices having this same config
            sorted_config = tuple(sorted(settings.items()))
            configs[category][sorted_config].append(device_name)
        # print groups of devices having the same config
        parts = []
        for category, category_label_info in self.category_labels.items():
            category_labels = category_label_info["labels"]
            if len(configs[category]) == 0:
                continue
            for sorted_config, device_names in configs[category].items():
                if category == "server":
                    sentence_start = "Server has"
                else:
                    sentence_start = format_sentence(
                        "%s has(have)",
                        device_names,
                        None,
                        category_labels[0],
                        category_labels[1],
                    )
                if len(sorted_config) == 0:
                    parts.append(sentence_start + " no config option available.\n")
                    continue
                msg = sentence_start + " the following config applied:\n"
                for setting_name, setting_value in sorted_config:
                    pprint = self.settings_table[setting_name].get("pretty_print")
                    if pprint is None:
                        if setting_value is None:
                            pprinted_value = PPRINT_NONE
                        else:
                            pprinted_value = str(setting_value)
                    else:
                        pprinted_value = pprint(setting_value)
                    msg += "%s=%s\n" % (setting_name, pprinted_value)
                parts.append(msg)
        requester.stdout.write("\n\n".join(parts) + "\n")


class PortSettingsManager:
    def __init__(self, server):
        self.server = server

    def _get_topology_ports(self, switch_mac):
        return self.server.db.execute(
            """select port1 as port, d2.name as peer
               from topology, devices d2
               where mac1 = %s
                 and port1 is not null
                 and d2.mac = mac2
               union
               select port2 as port, d1.name as peer
               from topology, devices d1
               where mac2=%s
                 and port2 is not null
                 and d1.mac = mac1""",
            (switch_mac, switch_mac))

    def _get_poeoff_ports(self, switch_mac):
        return self.server.db.select("poeoff", mac=switch_mac)

    def _get_named_ports(self, switch_mac):
        return self.server.db.select("switchports", mac=switch_mac)

    def _get_switch_info(self, requester, switch_name):
        device_info = self.server.devices.get_device_info(requester, switch_name)
        if device_info is None:
            return None
        if device_info.type != "switch":
            requester.stderr.write(f"Failed: {switch_name} is not a switch.\n")
            return None
        if not device_info.conf.get("lldp.explore", False):
            requester.stderr.write(f"Failed: cannot detect switch ports of {switch_name} "
                                   "because \"lldp.explore\" config option is not enabled.\n"
                                   "See: walt help show device-config\n")
            return None
        return device_info

    def get_writable_setting_names(self):
        return ("name",)

    def set_config(self, requester, switch_name, port_id, settings_args):
        # parse settings
        all_settings = parse_settings_args(requester, settings_args)
        if all_settings is None:
            return False
        port_name = None
        for k, v in all_settings.items():
            if k == "name":
                port_name = v
            else:
                requester.stderr.write(
                    "Failed: the only writable config item is `name=<port-name>`.\n"
                )
                return False
        # check name
        port_name_is_port_id = False
        if not re.match("^[a-zA-Z0-9-]+$", port_name):
            requester.stderr.write("Failed: the port name can only be made of digits, "
                                   "letters, and dashes (minus signs).\n")
            return False
        if re.match("^[0-9]+$", port_name):
            port_num = int(port_name)
            if port_num == port_id:
                port_name_is_port_id = True
            else:
                requester.stderr.write("Failed: to avoid confusion, the only "
                    f"""integer allowed for this port name is "{port_id}", """
                    "the ID of the port in the switch.\n")
                return False
        # check switch device
        device_info = self._get_switch_info(requester, switch_name)
        if device_info is None:
            return False
        switch_mac = device_info.mac
        # ok do the change
        if port_name_is_port_id:
            # table switchports only list names which are not the default
            self.server.db.delete("switchports", mac=switch_mac, port=port_id)
        else:
            curr_record = self.server.db.select_unique("switchports",
                    mac=switch_mac, port=port_id)
            if curr_record is None:
                self.server.db.insert("switchports",
                        mac=switch_mac, port=port_id, name=port_name)
            else:
                self.server.db.execute(
                        "UPDATE switchports "
                        "SET name = %s "
                        "WHERE mac = %s "
                        "  AND port = %s",
                        (port_name, switch_mac, port_id))
        requester.stdout.write("Done.\n")

    def get_config(self, requester, switch_name, port_id):
        device_info = self._get_switch_info(requester, switch_name)
        if device_info is None:
            return False
        footer_notes = []
        switch_mac = device_info.mac
        ports_info = defaultdict(dict)
        for topo in self._get_topology_ports(switch_mac):
            ports_info[topo.port]['peer'] = topo.peer
        for poeoff in self._get_poeoff_ports(switch_mac):
            ports_info[poeoff.port]['poeoff'] = poeoff.reason
        for swport in self._get_named_ports(switch_mac):
            ports_info[swport.port]['name'] = swport.name
        if port_id is None:
            port_ids = sorted(ports_info.keys())
            if len(port_ids) == 0:
                requester.stdout.write(f"WalT did not detect traffic going through this switch yet.\n")
                requester.stdout.write(f"Use 'walt device rescan' to probe again.\n")
                return
            requester.stdout.write(f"WalT currently uses the following ports of {switch_name}:\n")
            footer_notes.append("The other switch ports are in their default configuration.")
        else:
            requester.stdout.write(f"Port {port_id} of {switch_name} has the following config:\n")
            port_ids = [port_id]
        if device_info.conf.get("poe.reboots", False):
            poe_default = "on"
        else:
            poe_default = "unavailable"
            footer_notes.append(
                "PoE status is unavailable because the switch has its \"poe.reboots\" "
                "config option disabled "
                "(see: walt help show device-config).")
        for port_id in port_ids:
            notes = []
            peer = ports_info[port_id].get("peer", "unknown")
            poeoff_reason = ports_info[port_id].get("poeoff", None)
            if poeoff_reason is not None:
                poe = "off"
                notes.append(poeoff_reason)
            else:
                poe = poe_default
            name = ports_info[port_id].get("name", str(port_id))
            status = f"""{port_id}: name="{name}" poe={poe} peer={peer}"""
            if len(notes) > 0:
                notes = "; ".join(notes)
                status += f"  # {notes}"
            requester.stdout.write(status + '\n')
        if len(footer_notes) > 0:
            footer_notes = '\n'.join(footer_notes)
            requester.stdout.write(footer_notes + '\n')
