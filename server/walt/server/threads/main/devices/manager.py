#!/usr/bin/env python
from walt.server.threads.main.network.tools import set_static_ip_on_switch, \
                            ip_in_walt_network, get_walt_subnet, get_server_ip
from walt.server.threads.main.network.netsetup import NetSetup
from walt.common.tools import format_sentence, get_mac_address
from walt.server.tools import format_paragraph, to_named_tuple, merge_named_tuples
from walt.server import const
import re, json

DEVICE_NAME_NOT_FOUND="""No device with name '%s' found.\n"""

NEW_NAME_ERROR_AND_GUIDELINES = """\
Failed: invalid new name.
This name must be a valid network hostname.
Only alphanumeric characters and '-' are allowed.
The 1st character must be an alphabet letter.
(Example: rpi-D327)
"""

DEVICES_QUERY = """\
SELECT name, ip, mac, type from devices
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
            FROM devices d, switches s
            WHERE   d.mac = s.mac
            AND     s.lldp_explore = True
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
Use 'walt device admin <name>' to fix this."""

class DevicesManager(object):

    def __init__(self, db):
        self.db = db
        self.server_ip = get_server_ip()
        self.netmask = str(get_walt_subnet().netmask)

    def register_device(self, device_cls, **kwargs):
        """Derive device type from device class, then add or update, return True if new equipment."""
        if device_cls == None:
            kwargs['type'] = 'unknown'
        else:
            kwargs['type'] = device_cls.WALT_TYPE
            kwargs['model'] = device_cls.MODEL_NAME
        return self.add_or_update(**kwargs)

    def validate_device_name(self, requester, name):
        if self.get_device_info(requester, name, err_message = None) != None:
            requester.stderr.write("""Failed: a device with name '%s' already exists.\n""" % name)
            return False
        if not re.match('^[a-zA-Z][a-zA-Z0-9-]*$', name):
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
        if device_info == None and err_message != None:
            requester.stderr.write(err_message % device_name)
        return device_info

    def get_complete_device_info(self, mac):
        device_info = self.db.select_unique("devices", mac=mac)
        if device_info == None:
            return None
        device_type = device_info.type
        if device_type == 'node':
            node_info = self.db.select_unique("nodes", mac=mac)
            if node_info.netsetup == NetSetup.NAT:
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
        new_equipment = False
        modified = False
        db_data = self.db.select_unique("devices", mac=args_data['mac']);
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
                    if 'requester' in args_data:
                        requester = args_data['requester']
                        requester.stdout.write('Renaming %s to %s for clarity.\n' % (
                            db_data.name, name
                        ))
                # now we know its type, so we consider we have a new equipment here.
                new_equipment = True
                print 'Device: %s updating type, unknown -> %s' % (name, args_data['type'])
                updates['type'] = args_data['type']
            if db_data.ip is None and args_data['ip'] is not None:
                print 'Device: %s updating ip, unknown -> %s' % (name, args_data['ip'])
                updates['ip'] = args_data['ip']
            elif db_data.ip is not None and args_data['ip'] is not None and \
                    not ip_in_walt_network(db_data.ip) and ip_in_walt_network(args_data['ip']):
                # the device updated its IP by requesting our managed DHCP server
                print 'Device: %s updating ip, %s -> %s (now in walt network)' % (name, db_data.ip, args_data['ip'])
                updates['ip'] = args_data['ip']
            if len(updates) > 0:
                modified = True
                self.db.update("devices", 'mac', mac=args_data['mac'], **updates)
        else:
            # device was not known in db yet
            # generate a name for this device
            if 'name' not in args_data:
                args_data['name'] = self.generate_device_name(**args_data)
            print 'Device: %s is new, adding (%s, %s)' % (args_data['name'], args_data['ip'], args_data['type'])
            self.db.insert("devices", **args_data)
            modified = True
            if args_data['type'] != 'unknown':
                new_equipment = True
        # if new switch or node, insert in relevant table
        if new_equipment:
            if args_data['type'] == 'switch':
                self.db.insert('switches', **args_data)
            elif args_data['type'] == 'node':
                self.db.insert('nodes', **args_data)
        else:   # otherwise update them
            if args_data['type'] == 'switch':
                self.db.update('switches', 'mac', **args_data)
            elif args_data['type'] == 'node':
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

    def apply_switch_conf(self, requester, device_name, conf):
        device_info = self.get_device_info(requester, device_name)
        if device_info == None:
            return None # error already reported
        if device_info.type not in ('switch', 'unknown'):
            requester.stderr.write(
                'Cannot proceed because device is a %s.\n' % device_info.type)
            return
        device_info = device_info._asdict()
        device_info.update(
                requester = requester,
                type = 'switch',  # if it was 'unknown'
                ip = conf['ip'],
                lldp_explore = conf['allow_lldp_explore'],
                poe_reboot_nodes = conf['allow_poe_reboot'],
                snmp_conf = json.dumps(conf['snmp']))
        self.add_or_update(**device_info)

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

    def parse_device_set(self, requester, device_set):
        if ',' in device_set:
            devices = []
            for subset in device_set.split(','):
                subset_devices = self.parse_device_set(requester, subset)
                if subset_devices is None:
                    return None
                devices += subset_devices
            return devices
        elif device_set == 'server':
            server_mac = get_mac_address(const.WALT_INTF)
            # register the server in the device list, if missing
            self.add_or_update(
                    mac = server_mac, ip = str(get_server_ip()),
                type = 'server')
            return [self.get_complete_device_info(server_mac)]
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
            if len(devices) == 0:
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
