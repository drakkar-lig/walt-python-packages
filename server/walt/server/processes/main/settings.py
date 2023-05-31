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
)
from walt.server.tools import ip_in_walt_network


def uncapitalize(s):
    return s[0].lower() + s[1:]


def pprint_bool(bool_val):
    return str(bool_val).lower()


class SettingsManager:
    def __init__(self, server):
        self.server = server
        self.settings_table = {
            "netsetup": {
                "category": "walt-net-devices",
                "value-check": self.correct_netsetup_value,
                "default": int(NetSetup.LAN),
                "pretty_print": lambda int_val: NetSetup(int_val).readable_string(),
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
        try:
            int(setting_value)
            return True
        except ValueError:
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
            requester.stderr.write(
                f"Failed: '{setting_value}' is not a valid value for option 'disks'.\n"
                "        Use for example 'none', or '8G' (1 disk),"
                " '32G,1T' (2disks), etc.\n"
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

    def set_device_config(self, requester, device_set, settings_args):
        # parse settings
        all_settings = {}
        for arg in settings_args:
            parts = arg.split("=", maxsplit=1)
            if len(parts) != 2:
                requester.stderr.write(
                    "Provide settings as `<setting name>=<setting value>` arguments.\n"
                )
                return
            all_settings[parts[0]] = parts[1]

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
                should_reboot_devices = True  # update in DB (below) is enough
            elif setting_name == "ram":
                should_reboot_devices = True  # update in DB (below) is enough
            elif setting_name == "disks":
                should_reboot_devices = True  # update in DB (below) is enough
            elif setting_name == "networks":
                should_reboot_devices = True  # update in DB (below) is enough
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
                    device_info = device_info._asdict()
                    device_info.update(type=setting_value)
                    self.server.devices.add_or_update(
                        requester=requester, **device_info
                    )
                # 'type' is a column of table 'devices', so this setting should not
                # be recorded in 'devices.conf' column
                del db_settings["type"]

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
                    if setting_value is None:
                        pprinted_value = "<unspecified>"
                    else:
                        pprint = self.settings_table[setting_name].get("pretty_print")
                        if pprint is None:
                            pprinted_value = str(setting_value)
                        else:
                            pprinted_value = pprint(setting_value)
                    msg += "%s=%s\n" % (setting_name, pprinted_value)
                parts.append(msg)
        requester.stdout.write("\n\n".join(parts) + "\n")
