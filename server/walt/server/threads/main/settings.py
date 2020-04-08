import json, re
from collections import defaultdict
from walt.server.threads.main.network.netsetup import NetSetup
from walt.server.threads.main.nodes.manager import VNODE_DEFAULT_RAM, VNODE_DEFAULT_CPU_CORES
from walt.common.tools import do, format_sentence

class SettingsManager:
    def __init__(self, server):
        self.server = server
        self.settings_table = {
            'netsetup':         { 'category': 'nodes', 'value-check': self.correct_netsetup_value, 'default': int(NetSetup.LAN),
                                    'pretty_print': lambda int_val: NetSetup(int_val).readable_string() },
            'ram':              { 'category': 'virtual-nodes', 'value-check': self.correct_ram_value, 'default': VNODE_DEFAULT_RAM },
            'cpu.cores':        { 'category': 'virtual-nodes', 'value-check': self.correct_cpu_value, 'default': VNODE_DEFAULT_CPU_CORES },
            'type':             { 'category': 'unknown-devices', 'value-check': self.value_is_switch, 'default': 'unknown' },
            'lldp.explore':     { 'category': 'switches', 'value-check': self.correct_lldp_explore_value, 'default': False,
                                    'pretty_print': lambda bool_val: str(bool_val).lower() },
            'poe.reboots':      { 'category': 'switches', 'value-check': self.correct_poe_reboots_value, 'default': False,
                                    'pretty_print': lambda bool_val: str(bool_val).lower() },
            'snmp.version':     { 'category': 'switches', 'value-check': self.correct_snmp_version_value, 'default': None },
            'snmp.community':   { 'category': 'switches', 'value-check': self.correct_snmp_community_value, 'default': None }
        }
        self.category_checks = {
            'nodes':            self.applies_to_nodes,
            'virtual-nodes':    self.applies_to_virtual_nodes,
            'unknown-devices':  self.applies_to_unknown_devices,
            'switches':         self.applies_to_switches
        }

    def correct_snmp_community_value(self, requester, device_infos, setting_name, setting_value, all_settings):
        return True

    def correct_snmp_version_value(self, requester, device_infos, setting_name, setting_value, all_settings):
        if setting_value not in ('1', '2'):
            requester.stderr.write(
                "Failed: value of setting 'snmp.version' should be '1' or '2'.\n")
            return False
        return True

    def correct_bool_value(self, requester, setting_name, setting_value):
        if setting_value.lower() not in ('true', 'false'):
            requester.stderr.write(
                "Failed: setting '%s' only allows values 'true' or 'false'.\n" % setting_name)
            return False
        return True

    def correct_poe_reboots_value(self, requester, device_infos, setting_name, setting_value, all_settings):
        if not self.correct_bool_value(requester, setting_name, setting_value):
            return False
        if setting_value.lower() == 'true':
            # check that lldp.explore is also true, because for a PoE reboot we need to know where
            # the node is connected.
            lldp_explore = all_settings.get('lldp.explore')
            if lldp_explore is not None:
                if lldp_explore.lower() == 'true':
                    return True     # OK
                if lldp_explore.lower() == 'false':
                    requester.stderr.write(
                        "Failed: cannot set 'poe.reboots' to true unless 'lldp.explore' is set to true too.\n")
                    return False
            else:
                # lldp.explore was not specified on this command line,
                # look for it in existing configuration of all requested devices
                for device_info in device_infos:
                    lldp_explore = device_info.conf.get('lldp.explore')
                    if lldp_explore is None or lldp_explore is False:
                        requester.stderr.write(
                            "Failed: cannot set 'poe.reboots' to true unless 'lldp.explore' is set to true too.\n")
                        return False
        return True

    def correct_lldp_explore_value(self, requester, device_infos, setting_name, setting_value, all_settings):
        if not self.correct_bool_value(requester, setting_name, setting_value):
            return False
        if setting_value.lower() == 'true':
            # check that snmp conf is provided by other settings or was configured previously
            version_ok = 'snmp.version' in all_settings
            community_ok = 'snmp.community' in all_settings
            if version_ok and community_ok:
                return True
            # check if these settings were already set previously (whether we can find them in existing conf of
            # all requested devices).
            for device_info in device_infos:
                all_fine = True
                if version_ok is False:
                    all_fine = device_info.conf.get('snmp.version') is not None
                if community_ok is False:
                    all_fine = device_info.conf.get('snmp.community') is not None
                if not all_fine:
                    requester.stderr.write(
                        "Failed: cannot set 'lldp.explore' to true unless 'snmp.version' and 'snmp.community' are defined too.\n")
                    return False
        return True

    def value_is_switch(self, requester, device_infos, setting_name, setting_value, all_settings):
        if setting_value != 'switch':
            requester.stderr.write(
                "Failed: setting '%s' only allows value 'switch'.\n" % setting_name)
            return False
        return True

    def correct_cpu_value(self, requester, device_infos, setting_name, setting_value, all_settings):
        try:
            int(setting_value)
            return True
        except ValueError:
            requester.stderr.write(
                "Failed: '%s' is not a valid value for cpu.cores (expecting for instance 1 or 4).\n" % setting_value)
            return False

    def correct_ram_value(self, requester, device_infos, setting_name, setting_value, all_settings):
        if re.match(r'\d+[MG]', setting_value) is None:
            requester.stderr.write(
                "Failed: '%s' is not a valid value for ram (expecting for instance 512M or 1G).\n" % setting_value)
            return False
        return True

    def correct_netsetup_value(self, requester, device_infos, setting_name, setting_value, all_settings):
        try:
            NetSetup(setting_value)
            return True
        except ValueError:
            requester.stderr.write(
                "Failed: netsetup value should be 'NAT' or 'LAN'.\n")
            return False

    def applies_to_unknown_devices(self, requester, device_infos, setting_name, setting_value, all_settings):
        not_unknown = [di for di in device_infos if di.type != "unknown"]
        if len(not_unknown) > 0:
            requester.stderr.write("Failed: setting '" + setting_name + "' can only be applied to unknown devices.\n")
            return False
        return True

    def applies_to_switches(self, requester, device_infos, setting_name, setting_value, all_settings):
        # if we have another setting 'type=switch', then we are expecting unknown devices, and this
        # will be verified by the appropriate check for this other setting.
        if all_settings.get('type') == 'switch':
            return True     # ok for us
        not_switches = [di for di in device_infos if di.type != "switch"]
        if len(not_switches) > 0:
            msg = format_sentence("Failed: %s is(are) not a() switch(switches), "
                                  "so '" + setting_name + "' setting cannot be applied.\n",
                                  [d.name for d in not_switches],
                                  None, 'Device', 'Devices')
            requester.stderr.write(msg)
            return False
        return True

    def applies_to_nodes(self, requester, device_infos, setting_name, setting_value, all_settings):
        not_nodes = [di for di in device_infos if di.type != "node"]
        if len(not_nodes) > 0:
            msg = format_sentence("Failed: %s is(are) not a() node(nodes), "
                                  "so it(they) does(do) not support the '" + setting_name + "' setting.\n",
                                  [d.name for d in not_nodes],
                                  None, 'Device', 'Devices')
            requester.stderr.write(msg)
            return False
        return True

    def applies_to_virtual_nodes(self, requester, device_infos, setting_name, setting_value, all_settings):
        if not self.applies_to_nodes(requester, device_infos, setting_name, setting_value, all_settings):
            return False
        not_virtual_node = [di for di in device_infos if not di.virtual]
        if len(not_virtual_node) > 0:
            msg = format_sentence("Failed: %s is(are) not virtual, "
                                  "so it(they) does(do) not support the '" + setting_name + "' setting.\n",
                                  [d.name for d in not_virtual_node],
                                  None, 'Node', 'Nodes')
            requester.stderr.write(msg)
            return False
        return True

    def set_device_config(self, requester, device_set, settings_args):
        # parse settings
        all_settings = {}
        for arg in settings_args:
            parts = arg.split('=')
            if len(parts) != 2:
                requester.stderr.write(
                "Provide settings as `<setting name>=<setting value>` arguments.\n")
                return
            all_settings[parts[0]] = parts[1]

        # ensure the device set is correct
        device_infos = self.server.devices.parse_device_set(requester, device_set)
        if device_infos is None:
            return  # issue already reported

        # ensure all settings are known and pass related checks
        for setting_name, setting_value in all_settings.items():

            # check the setting is known
            setting_info = self.settings_table.get(setting_name)
            if setting_info is None:
                requester.stderr.write(
                    "Unknown setting '%s'. See: 'walt help show device-config'\n" % setting_name)
                return

            # verify this setting pass all checks
            category_check = self.category_checks[setting_info['category']]
            if not category_check(requester, device_infos, setting_name, setting_value, all_settings):
                return
            value_check = setting_info['value-check']
            if not value_check(requester, device_infos, setting_name, setting_value, all_settings):
                return

        # effectively configure the devices
        should_reboot_nodes = False
        db_settings = all_settings.copy()
        for setting_name, setting_value in all_settings.items():
            if setting_name == 'netsetup':
                new_netsetup_state = NetSetup(setting_value)
                for node_info in device_infos:
                    if node_info.conf.get('netsetup', 0) == new_netsetup_state:
                        # skip this node: already configured
                        continue
                    # update iptables
                    do("iptables %(action)s WALT --source '%(ip)s' --jump ACCEPT" %
                       dict(ip=node_info.ip,
                            action="--insert" if new_netsetup_state == NetSetup.NAT else "--delete"))
                db_settings['netsetup'] = int(new_netsetup_state)
                should_reboot_nodes = True
            elif setting_name == 'cpu.cores':
                db_settings['cpu.cores'] = int(setting_value)
                should_reboot_nodes = True  # update in DB (below) is enough
            elif setting_name == 'ram':
                should_reboot_nodes = True  # update in DB (below) is enough
            elif setting_name in ('lldp.explore', 'poe.reboots'):
                setting_value = (setting_value.lower() == 'true')   # convert value to boolean
                db_settings[setting_name] = setting_value
            elif setting_name == 'snmp.version':
                db_settings[setting_name] = int(setting_value)
            elif setting_name == 'snmp.community':
                pass    # update in DB (below) is enough
            elif setting_name == 'type':
                for device_info in device_infos:
                    device_info = device_info._asdict()
                    device_info.update(
                        requester = requester,
                        type = setting_value)
                    self.server.devices.add_or_update(**device_info)
                # 'type' is a column of table 'devices', so this setting should not
                # be recorded in 'devices.conf' column
                del db_settings['type']

        # save in db
        new_vals = json.dumps(db_settings)
        for di in device_infos:
            self.server.db.execute("update devices set conf = conf || %s::jsonb where mac = %s",
                            (new_vals, di.mac))
        self.server.db.commit()

        # notify user
        if should_reboot_nodes:
            requester.stdout.write('Done. Reboot node(s) to see new settings in effect.\n')
        else:
            requester.stdout.write('Done.\n')

    def get_device_config(self, requester, device_set):
        # ensure the device set is correct
        device_infos = self.server.devices.parse_device_set(requester, device_set)
        if device_infos is None:
            return  # issue already reported
        configs = defaultdict(lambda: defaultdict(list))
        for device_info in device_infos:
            # check device category
            secondary_category = None
            if device_info.type == 'unknown':
                category = 'unknown-devices'
            elif device_info.type == 'switch':
                category = 'switches'
            elif device_info.type == 'node':
                if device_info.virtual:
                    category = 'virtual-nodes'
                    secondary_category = 'nodes'
                else:
                    category = 'nodes'
            elif device_info.type == 'server':
                category = 'server'
            else:
                raise NotImplementedError('Unexpected device type in get_device_config().')
            # retrieve device settings
            settings = dict(device_info.conf)
            # add default value of unspecified settings
            for setting_name, setting_info in self.settings_table.items():
                if setting_info['category'] in (category, secondary_category) \
                        and setting_name not in settings:
                    settings[setting_name] = setting_info['default']
            # append to the list of devices having this same config
            sorted_config = tuple(sorted(settings.items()))
            configs[category][sorted_config].append(device_info.name)
        # print groups of devices having the same config
        parts = []
        for category, category_labels in (
                ('nodes', ('Node', 'Nodes')),
                ('virtual-nodes', ('Virtual node', 'Virtual nodes')),
                ('switches', ('Switch', 'Switches')),
                ('server', None),
                ('unknown-devices', ('Unknown device', 'Unknown devices'))):
            if len(configs[category]) == 0:
                continue
            for sorted_config, device_names in configs[category].items():
                if category == 'server':
                    sentence_start = 'Server has'
                else:
                    sentence_start = format_sentence('%s has(have)', device_names,
                                None, category_labels[0], category_labels[1])
                if len(sorted_config) == 0:
                    parts.append(sentence_start + ' no config option available.\n')
                    continue
                msg = sentence_start + ' the following config applied:\n'
                for setting_name, setting_value in sorted_config:
                    if setting_value is None:
                        pprinted_value = '<unspecified>'
                    else:
                        pprint = self.settings_table[setting_name].get('pretty_print')
                        if pprint is None:
                            pprinted_value = str(setting_value)
                        else:
                            pprinted_value = pprint(setting_value)
                    msg += '%s=%s\n' % (setting_name, pprinted_value)
                parts.append(msg)
        requester.stdout.write('\n\n'.join(parts) + '\n')
