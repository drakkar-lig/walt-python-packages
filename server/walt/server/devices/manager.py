#!/usr/bin/env python

from walt.server.devices.topology import Topology
from walt.server import snmp
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
        self.topology = Topology(db)

    def rescan(self, **kwargs):
        self.topology.rescan(**kwargs)

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

    def add(self, **kwargs):
        self.topology.add_device(**kwargs)

    def is_reachable(self, requester, device_name):
        res = self.get_device_info(requester, device_name)
        if res == None:
            return
        return res.reachable != 0

    def node_bootup_event(self, node_ip):
        # if we got this event, then the node is reachable
        self.db.update('devices', 'ip', ip=node_ip, reachable=1)
        self.db.commit()
