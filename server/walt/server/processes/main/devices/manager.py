import re

from walt.common.formatting import format_paragraph, format_sentence
from walt.common.tools import get_mac_address
from walt.server import const
from walt.server.processes.main.network.netsetup import NetSetup
from walt.server.tools import ip_in_walt_network, get_walt_subnet, \
                              to_named_tuple, merge_named_tuples, get_server_ip

DEVICE_NAME_NOT_FOUND="""No device with name '%s' found.\n"""

NEW_NAME_ERROR_AND_GUIDELINES = """\
Failed: invalid new name.
This name must be a valid network hostname.
Only alphanumeric characters and '-' are allowed.
The 1st character must be an alphabet letter.
The name must be at least 2-chars long.
(Example: rpi-D327)
"""

DEVICES_QUERY = """\
SELECT name, ip, mac,
       CASE WHEN type = 'node' AND virtual THEN 'node (virtual)'
            WHEN type = 'node' AND mac like '52:54:00:%%' THEN 'node (vpn)'
            WHEN type = 'node' THEN 'node (physical)'
            ELSE type
       END as type
FROM devices
WHERE type %(unknown_op)s 'unknown'
ORDER BY type, name;"""

MY_NODES_QUERY = """\
SELECT  d.mac as mac
FROM devices d, nodes n, images i
WHERE   d.mac = n.mac
AND     n.image = i.fullname
AND     i.ready = True
AND     split_part(n.image, '/', 1) = '%s'
ORDER BY name;"""

DEVICE_SET_QUERIES = {
        'all-nodes': """
            SELECT  d.mac as mac
            FROM devices d, nodes n, images i
            WHERE   d.mac = n.mac
            AND     n.image = i.fullname
            AND     i.ready = True
            ORDER BY d.name;""",
        'all-switches': """
            SELECT  d.mac as mac
            FROM devices d
            WHERE   d.type = 'switch'
            ORDER BY name;""",
        'all-devices': """
            SELECT  d.mac as mac
            FROM devices d
            ORDER BY type, name;""",
        'explorable-switches': """
            SELECT  d.mac as mac
            FROM devices d
            WHERE   d.type = 'switch'
            AND     COALESCE((d.conf->'lldp.explore')::boolean, False) = True
            ORDER BY d.name;"""
}

TITLE_DEVICE_SHOW_MAIN = """\
The WalT network contains the following devices:"""

FOOTNOTE_DEVICE_SHOW_MAIN = """\
tips:
- use 'walt device tree' for a tree view of the network
- use 'walt device forget <device_name>' to make WalT forget about an obsolete device"""

TITLE_SOME_UNKNOWN_DEVICES = """\
WalT also detected the following devices but could not detect their type:"""

FOOTNOTE_SOME_UNKNOWN_DEVICES = """\
If one of them is actually a switch, use 'walt device config <name> type=switch' to fix this."""

class DevicesManager(object):

    def __init__(self, server):
        self.db = server.db
        self.logs = server.logs
        self.server_ip = get_server_ip()
        self.netmask = str(get_walt_subnet().netmask)
        self._server_mac = None

    @property
    def server_mac(self):
        return self.get_server_mac()

    def get_server_mac(self):
        if self._server_mac is None:
            self._server_mac = get_mac_address(const.WALT_INTF)
            # register the server in the device list, if missing
            self.add_or_update(
                    mac = self._server_mac, ip = str(self.server_ip),
                    type = 'server')
        return self._server_mac

    def validate_device_name(self, requester, name):
        if self.get_device_info(requester, name, err_message = None) != None:
            if requester is not None:
                requester.stderr.write("""Failed: a device with name '%s' already exists.\n""" % name)
            return False
        if len(name) < 2 or not re.match('^[a-zA-Z][a-zA-Z0-9-]*$', name):
            if requester is not None:
                requester.stderr.write(NEW_NAME_ERROR_AND_GUIDELINES)
            return False
        return True

    def rename(self, requester, old_name, new_name):
        device_info = self.get_device_info(requester, old_name)
        if device_info == None:
            return
        if not self.validate_device_name(requester, new_name):
            return
        # all is fine, let's update it
        self.db.update("devices", 'mac', mac = device_info.mac, name = new_name)
        self.db.commit()

    def get_type(self, mac):
        device_info = self.db.select_unique("devices", mac=mac)
        if not device_info:
            return None
        return device_info.type

    def get_device_info(self, requester, device_name, \
                        err_message = DEVICE_NAME_NOT_FOUND):
        device_info = self.db.select_unique("devices", name=device_name)
        if device_info == None and err_message != None and requester is not None:
            requester.stderr.write(err_message % device_name)
        return device_info

    def get_complete_device_info(self, mac):
        device_info = self.db.select_unique("devices", mac=mac)
        if device_info == None:
            return None
        device_type = device_info.type
        if device_type == 'node':
            node_info = self.db.select_unique("nodes", mac=mac)
            if device_info.conf.get('netsetup', 0) == NetSetup.NAT:
                gateway = self.server_ip
            else:
                gateway = ''
            node_info = to_named_tuple(node_info._asdict())
            node_info = node_info.update(
                gateway = gateway,
                netmask = self.netmask
            )
            device_info = merge_named_tuples(device_info, node_info)
        elif device_type == 'switch':
            switch_info = self.db.select_unique("switches", mac=mac)
            device_info = merge_named_tuples(device_info, switch_info)
        return device_info

    def get_name_from_ip(self, ip):
        device_info = self.db.select_unique("devices", ip=ip)
        if device_info is None:
            return None
        return device_info.name

    def notify_unknown_ip(self, requester, device_name):
        requester.stderr.write('Sorry, IP address of %s in unknown.\n' \
                            % device_name)

    def get_device_ip(self, requester, device_name):
        device_info = self.get_device_info(requester, device_name)
        if device_info == None:
            return None # error already reported
        if device_info.ip == None:
            self.notify_unknown_ip(requester, device_name)
        return device_info.ip

    def generate_device_name(self, type, mac, **kwargs):
        if type == 'server':
            return 'walt-server'
        else:
            prefix = "%s-%s" % (type, "".join(mac.split(':')[3:]))
            i = 1
            while True:
                if i == 1:
                    name = prefix
                else:
                    name = "%s-%d" % (prefix, i)
                device_info = self.db.select_unique("devices", name=name)
                if device_info == None:
                    # ok name does not exist in db yet
                    return name
                else:
                    # device name already exists! Check next one.
                    i += 1

    def add_or_update(self, **args_data):
        """Return True if a new equipment (node, switch) was identified, False otherwise"""
        if 'type' not in args_data:
            args_data['type'] = 'unknown'
        new_equipment = False
        modified = False
        newly_identified = False
        db_data = self.db.select_unique("devices", mac=args_data['mac'])
        if db_data:
            # -- device found in db
            updates = {}
            name = db_data.name
            if db_data.type == 'unknown' and args_data['type'] != 'unknown':
                # device was in db, but type was unknown.
                if 'unknown' in db_data.name:
                    # device name has not been updated by the user,
                    # we will generate a new one more appropriate for the new type
                    name = self.generate_device_name(**args_data)
                    updates['name'] = name
                    self.logs.platform_log('devices', f'renamed {db_data.name} to {name} for clarity')
                    if 'requester' in args_data:
                        requester = args_data['requester']
                        requester.stdout.write(f'Renaming {db_data.name} to {name} for clarity.\n')
                # now we know its type, so we consider we have a new equipment here.
                new_equipment = True
                newly_identified = True
                print('Device: %s updating type, unknown -> %s' % (name, args_data['type']))
                updates['type'] = args_data['type']
            if db_data.ip is None and args_data['ip'] is not None:
                print('Device: %s updating ip, unknown -> %s' % (name, args_data['ip']))
                updates['ip'] = args_data['ip']
            elif db_data.ip is not None and args_data['ip'] is not None and \
                    not ip_in_walt_network(db_data.ip) and ip_in_walt_network(args_data['ip']):
                # the device updated its IP by requesting our managed DHCP server
                print('Device: %s updating ip, %s -> %s (now in walt network)' % (name, db_data.ip, args_data['ip']))
                updates['ip'] = args_data['ip']
            if len(updates) > 0:
                modified = True
                self.db.update("devices", 'mac', mac=args_data['mac'], **updates)
        else:
            # device was not known in db yet
            # generate a name for this device
            if 'name' not in args_data:
                args_data['name'] = self.generate_device_name(**args_data)
            print('Device: %s is new, adding (%s, %s)' % (args_data['name'], args_data['ip'], args_data['type']))
            self.db.insert("devices", **args_data)
            modified = True
            new_equipment = True
        # if new switch or node, insert in relevant table
        # and submit platform logline
        db_data = self.db.select_unique("devices", mac=args_data['mac'])    # refresh after prev updates
        if new_equipment:
            if newly_identified:
                ident_log_line = f" (device type previously unknown)"
            else:
                ident_log_line = ""
            if db_data.type == 'switch':
                self.db.insert('switches', **args_data)
                dtype = "switch"
                details = ""
            elif db_data.type == 'node':
                self.db.insert('nodes', **args_data)
                dtype = "node"
                details = f" model={args_data['model']}"
            else:
                dtype = "device"
                details = f" type={db_data.type}"
            info = f"name={db_data.name}{details} mac={db_data.mac} ip={db_data.ip}"
            logline = f"new {dtype}{ident_log_line} {info}"
            self.logs.platform_log('devices', logline)
        else:   # otherwise update them
            if db_data.type == 'switch':
                self.db.update('switches', 'mac', **args_data)
            elif db_data.type == 'node':
                self.db.update('nodes', 'mac', **args_data)
        if modified:
            self.db.commit()
        return new_equipment

    def show(self):
        q = DEVICES_QUERY % dict(unknown_op = '!=')
        msg = format_paragraph(
                TITLE_DEVICE_SHOW_MAIN,
                self.db.pretty_printed_select(q),
                FOOTNOTE_DEVICE_SHOW_MAIN)
        unknown_devices = self.db.select('devices', type='unknown')
        if len(unknown_devices) > 0:
            q = DEVICES_QUERY % dict(unknown_op = '=')
            msg += format_paragraph(
                        TITLE_SOME_UNKNOWN_DEVICES,
                        self.db.pretty_printed_select(q),
                        FOOTNOTE_SOME_UNKNOWN_DEVICES)
        return msg

    def includes_devices_not_owned(self, requester, device_set, warn):
        username = requester.get_username()
        if not username:
            return False    # client already disconnected, give up
        devices = self.parse_device_set(requester, device_set)
        if devices is None:
            return None
        not_owned = [d for d in devices
                     if not (d.type == "node" and
                             (d.image.startswith(username + '/') or d.image.startswith('waltplatform/'))
                             or d.type != "node")]
        if len(not_owned) == 0:
            return False
        else:
            if warn:
                requester.stderr.write(format_sentence(
                    'Warning: %s seems(seem) to be used by another(other) user(users).',
                    [d.name for d in not_owned], "No device", "Device", "Devices") + '\n')
            return True

    def parse_device_set(self, requester, device_set, allowed_device_set=None, allow_empty=False):
        devices = []
        if ',' in device_set:
            for subset in device_set.split(','):
                subset_devices = self.parse_device_set(requester, subset, allow_empty=True)
                if subset_devices is None:
                    return None
                devices += subset_devices
        elif device_set == 'server':
            devices = [self.get_complete_device_info(self.server_mac)]
        else:
            username = requester.get_username()
            if not username:
                return None    # client already disconnected, give up
            # check keywords
            sql = None
            if device_set is None or device_set == 'my-nodes':
                sql = MY_NODES_QUERY % username
            elif device_set in DEVICE_SET_QUERIES:
                sql = DEVICE_SET_QUERIES[device_set]
            if sql is not None:
                # retrieve devices from database
                device_macs = [record[0] for record in self.db.execute(sql)]
            else:
                # otherwise a specific device is requested by name
                dev_name = device_set
                dev_info = self.get_device_info(requester, dev_name)
                if dev_info is None:
                    return None
                device_macs = [ dev_info.mac ]
            # get complete devices info
            devices = [self.get_complete_device_info(mac) for mac in device_macs]
        # verify selected devices are allowed
        if allowed_device_set is not None:
            allowed_dev_names = set(d.name for d in self.parse_device_set(requester, allowed_device_set))
            for d in devices:
                if d.name not in allowed_dev_names:
                    requester.stderr.write(f"Invalid value '{device_set}'; allowed devices belong to '{allowed_device_set}'\n")
                    return None
        if len(devices) == 0 and not allow_empty:
            requester.stderr.write('No matching devices found! (tip: walt help show node-terminology)\n')
            return None
        return sorted(devices)

    def as_device_set(self, names):
        return ','.join(sorted(names))

    def develop_device_set(self, requester, device_set):
        devices = self.parse_device_set(requester, device_set)
        if devices is None:
            return None
        return self.as_device_set(d.name for d in devices)

    def get_connectivity_info(self, device_mac):
        # we look for a record where mac1 or mac2 equals device_mac
        records = list(self.db.select("topology", mac1=device_mac))
        records += list(self.db.select("topology", mac2=device_mac))
        if len(records) != 1:
            return (None, None)
        record = records[0]
        if record.mac1 == device_mac:
             switch_mac, switch_port = record.mac2, record.port2
        else:
             switch_mac, switch_port = record.mac1, record.port1
        switch_info = self.get_complete_device_info(switch_mac)
        return switch_info, switch_port
