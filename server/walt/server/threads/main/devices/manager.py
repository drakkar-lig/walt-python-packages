#!/usr/bin/env python

from walt.server.threads.main.network.tools import set_static_ip_on_switch, \
                                                    ip_in_walt_network
from walt.server.tools import format_paragraph
import re

DEVICE_NAME_NOT_FOUND="""No device with name '%s' found.\n"""

NEW_NAME_ERROR_AND_GUIDELINES = """\
Failed: invalid new name.
This name must be a valid network hostname.
Only alphanumeric characters and '-' are allowed.
The 1st character must be an alphabet letter.
(Example: rpi-D327)
"""

DEVICES_QUERY = """select * from devices order by type, name;"""

TITLE_DEVICE_SHOW_MAIN = """\
The WalT network contains the following devices:"""

FOOTNOTE_DEVICE_SHOW_MAIN = """\
tips:
- use 'walt device tree' for a tree view of the network
- use 'walt device forget <device_name>' to make WalT forget about an obsolete device"""

class DevicesManager(object):

    def __init__(self, db):
        self.db = db

    def register_device(self, device_cls, ip, mac):
        """Derive device type from device type, then add or update, return True if new equipment."""
        kwargs = dict(
            mac=mac,
            ip=ip
        )
        if device_cls == None:
            kwargs['device_type'] = 'unknown'
        else:
            kwargs['device_type'] = device_cls.WALT_TYPE
            kwargs['model'] = device_cls.MODEL_NAME
            if device_cls.WALT_TYPE == 'switch':
                print 'Switch: assigning static IP configuration %s (%s)...' % (ip, mac)
                #set_static_ip_on_switch(ip)
        return self.add_or_update(**kwargs)

    def rename(self, requester, old_name, new_name):
        device_info = self.get_device_info(requester, old_name)
        if device_info == None:
            return
        if self.get_device_info(requester, new_name, err_message = None) != None:
            requester.stderr.write("""Failed: a device with name '%s' already exists.\n""" % new_name)
            return
        if not re.match('^[a-zA-Z][a-zA-Z0-9-]*$', new_name):
            requester.stderr.write(NEW_NAME_ERROR_AND_GUIDELINES)
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

    def generate_device_name(self, device_type, mac, **kwargs):
        if device_type == 'server':
            return 'walt-server'
        else:
            return "%s-%s" %(
                device_type,
                "".join(mac.split(':')[3:]))

    def add_or_update(self, **args_data):
        """Return True if a new equipment (node, switch) was identified, False otherwise"""
        new_equipment = False
        modified = False
        db_data = self.db.select_unique("devices", mac=args_data['mac']);
        args_data['type'] = args_data['device_type']  # db column name is 'type'
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
                # now we know its type, so we consider we have a new equipment here.
                new_equipment = True
                print 'Device: %s updating type, unknown -> %s' % (name, args_data['type'])
                updates['type'] = args_data['type']
            if not ip_in_walt_network(db_data.ip) and ip_in_walt_network(args_data['ip']):
                # the device updated its IP by requesting our managed DHCP server
                print 'Device: %s updating ip, %s -> %s (now in walt network)' % (name, db_data.ip, args_data['ip'])
                updates['ip'] = args_data['ip']
            if len(updates) > 0:
                modified = True
                self.db.update("devices", 'mac', mac=args_data['mac'], **updates)
        else:
            # device was not known in db yet
            # generate a name for this device
            args_data['name'] = self.generate_device_name(**args_data)
            print 'Device: %s is new, adding (%s, %s)' % (args_data['name'], args_data['ip'], args_data['type'])
            self.db.insert("devices", **args_data)
            modified = True
            if args_data['type'] != 'unknown':
                new_equipment = True
        # if new switch or node, call relevant code
        if new_equipment:
            if args_data['type'] == 'switch':
                self.db.insert('switches', **args_data)
            elif args_data['type'] == 'node':
                self.db.insert('nodes', **args_data)
        if modified:
            self.db.commit()
        return new_equipment

    def is_reachable(self, requester, device_name):
        res = self.get_device_info(requester, device_name)
        if res == None:
            return
        return res.reachable != 0

    def node_bootup_event(self, node_ip):
        # if we got this event, then the node is reachable
        self.db.update('devices', 'ip', ip=node_ip, reachable=1)
        self.db.commit()

    def show(self):
        return format_paragraph(
                TITLE_DEVICE_SHOW_MAIN,
                self.db.pretty_printed_select(DEVICES_QUERY),
                FOOTNOTE_DEVICE_SHOW_MAIN)

