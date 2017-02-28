#!/usr/bin/env python

from walt.server.threads.main.network.tools import set_static_ip_on_switch
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
        """Derive device type from device type, then add or update"""
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

    def add_or_update(self, **kwargs):
        """Return False if device exists and unmodified, True if device created or updated"""
        device = self.db.select_unique("devices", mac=kwargs['mac']);
        kwargs['type'] = kwargs['device_type']  # db column name is 'type'
        if device:
            if (kwargs['ip'] != device.ip) or (kwargs['type'] != device.type):
                print 'Device: %s has changed, updating (%s, %s) to (%s, %s)' % \
                    (device.name, device.ip, device.type, kwargs['ip'], kwargs['type'])
                self.db.update("devices", 'mac', **kwargs)
            else:
                print 'Device: %s exists' % device.name
                return False
        else:
            # generate a name for this device
            kwargs['name'] = self.generate_device_name(**kwargs)
            print 'Device: %s is new, adding (%s, %s)' % (kwargs['name'], kwargs['ip'], kwargs['type'])
            self.db.insert("devices", **kwargs)
            # if switch or node, insert in relevant table
            if device_type == 'switch':
                self.db.insert('switches', **kwargs)
            elif device_type == 'node':
                self.db.insert('nodes', **kwargs)
        self.db.commit()
        return True

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

