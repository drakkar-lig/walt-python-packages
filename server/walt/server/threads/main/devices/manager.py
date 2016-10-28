#!/usr/bin/env python

from walt.server.threads.main.network.tools import set_static_ip_on_switch
import re

DEVICE_NAME_NOT_FOUND="""No device with name '%s' found.\n"""

NEW_NAME_ERROR_AND_GUIDELINES = """\
Failed: invalid new name.
This name must be a valid network hostname.
Only alphanumeric characters and '-' are allowed.
The 1st character must be an alphabet letter.
(Example: rpi-D327)
"""

class DevicesManager(object):

    def __init__(self, db):
        self.db = db

    def register_device(self, device_cls, ip, mac):
        # insert in table devices if missing
        if self.db.select_unique("devices", mac=mac):
            return False
        else:
            if device_cls == None:
                device_type = 'unknown'
            else:
                device_type = device_cls.WALT_TYPE
            kwargs = dict(
                mac=mac,
                ip=ip,
                device_type=device_type
            )
            if device_cls != None:
                if device_cls.WALT_TYPE == 'switch':
                    print 'Affecting static IP configuration on switch %s (%s)...' % \
                        (ip, mac)
                    set_static_ip_on_switch(ip)
                    kwargs['model'] = device_cls.MODEL_NAME
                elif device_cls.WALT_TYPE == 'node':
                    kwargs['model'] = device_cls.MODEL_NAME
            self.add_if_missing(**kwargs)
            return True     # device added

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

    def add_if_missing(self, **kwargs):
        if self.db.select_unique("devices", mac=kwargs['mac']):
            return False
        else:
            device_type = kwargs['device_type']
            kwargs['type'] = device_type    # db column name is 'type'
            # generate a name for this device
            kwargs['name'] = self.generate_device_name(**kwargs)
            # insert a new row
            self.db.insert("devices", **kwargs)
            # if switch or node, insert in relevant table
            if device_type == 'switch':
                self.db.insert('switches', **kwargs)
            elif device_type == 'node':
                self.db.insert('nodes', **kwargs)
            # that's it.
            self.db.commit()
            return True

    def add_or_update(self, **kwargs):
        if self.db.select_unique("devices", mac=kwargs['mac']):
            # device already exists, update it
            device_type = kwargs['device_type']
            kwargs['type'] = device_type    # db column name is 'type'
            self.db.update("devices", 'mac', **kwargs)
        else:
            self.add_if_missing(**kwargs)
        self.db.commit()

    def is_reachable(self, requester, device_name):
        res = self.get_device_info(requester, device_name)
        if res == None:
            return
        return res.reachable != 0

    def node_bootup_event(self, node_ip):
        # if we got this event, then the node is reachable
        self.db.update('devices', 'ip', ip=node_ip, reachable=1)
        self.db.commit()
