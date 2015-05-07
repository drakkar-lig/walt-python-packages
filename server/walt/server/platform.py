#!/usr/bin/env python

import snmp, time, const
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

    def reboot_node(self, requester, node_name):
        connectivity_info = \
            self.topology.get_connectivity_info(requester, node_name)
        if connectivity_info == None:
            return None # error already reported
        # all is fine, let's reboot it
        self.poe_reboot_port(**connectivity_info)
        requester.write_stdout('done.\n')

    def rename_device(self, requester, old_name, new_name):
        self.topology.rename_device(requester, old_name, new_name)

    def poe_reboot_port(self, switch_ip, switch_port):
        proxy = snmp.Proxy(switch_ip, poe=True)
        proxy.poe.set_port(switch_port, False)
        time.sleep(const.POE_REBOOT_DELAY)
        proxy.poe.set_port(switch_port, True)

    def register_node(self, node_ip):
        self.topology.register_node(node_ip)

