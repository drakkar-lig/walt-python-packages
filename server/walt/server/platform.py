#!/usr/bin/env python

import snmp, time
from walt.server.topology import Topology

class Platform(object):

    def __init__(self, db):
        self.db = db
        self.topology = Topology(db)

    def update(self, requester=None):
        self.topology.update(requester)

    def describe(self, details=False):
        if details:
            return self.topology.printed_as_detailed_table()
        else:
            return self.topology.printed_as_tree()

    def setpower(self, requester, node_name, poweron):
        connectivity_info = \
            self.topology.get_connectivity_info(requester, node_name)
        if connectivity_info == None:
            return False # error already reported
        # all is fine, let's do it
        switch_ip = connectivity_info['switch_ip']
        switch_port = connectivity_info['switch_port']
        proxy = snmp.Proxy(switch_ip, poe=True)
        proxy.poe.set_port(switch_port, poweron)
        return True

    def rename_device(self, requester, old_name, new_name):
        self.topology.rename_device(requester, old_name, new_name)

