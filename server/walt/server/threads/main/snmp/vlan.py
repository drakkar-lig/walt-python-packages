#!/usr/bin/env python
from walt.server.threads.main.snmp.base import load_mib, PortsBitField

Q_BRIDGE_MIB_CreateAndGo = 4

class PortConfig(object):
    def __init__(self, port):
        self.port = port
        self.default_vlan_id = 1
        self.egress_vlans = set([ 1 ])
        self.untagged_vlans = set([ 1 ])
    def trunk(self, vlan_id_set, native_vlan_id = None):
        self.egress_vlans = set(vlan_id_set)
        self.untagged_vlans = set([])
        if native_vlan_id != None:
            self.egress_vlans.add(native_vlan_id)
            self.untagged_vlans.add(native_vlan_id)
            self.default_vlan_id = native_vlan_id
        return self
    def access(self, vlan_id):
        self.default_vlan_id = vlan_id
        self.egress_vlans = set([vlan_id])
        self.untagged_vlans = set([vlan_id])
        return self

class SwitchConfig(object):
    def __init__(self):
        self.port_configs = set([])
        self.registered_vlans = {}
    def register_vlan(self, vlan_id, vlan_name):
        self.registered_vlans[vlan_id] = vlan_name
    def add_port_config(self, port_config):
        self.port_configs.add(port_config)

class VlanProxy(object):
    def __init__(self, snmp_proxy):
        load_mib("Q-BRIDGE-MIB")
        self.snmp = snmp_proxy
    def get_existing_vlans(self):
        static_vlans = dict(self.snmp.dot1qVlanStaticName)
        existing_vlans = {}
        for vlan_id in [ int(k[1]) for k in self.snmp.dot1qVlanStatus.keys() ]:
            if vlan_id in static_vlans:
                existing_vlans[vlan_id] = { 'preconfigured': False,
                                            'name': str(static_vlans[vlan_id]) }
            else:
                existing_vlans[vlan_id] = { 'preconfigured': True }
        return existing_vlans
    def vlan_exists(self, vlan_name):
        return vlan_name in self.snmp.dot1qVlanStaticName.values()
    def apply_config_to_device(self, config):
        print 'setting the default vlan id on each port...'
        for port_config in config.port_configs:
            self.snmp.dot1qPvid[port_config.port] = port_config.default_vlan_id
        print 'configuring vlans...'
        existing_vlans = self.get_existing_vlans()
        for vlan_id in config.registered_vlans:
            print 'vlan', vlan_id
            # create missing vlans and update vlan names.
            # note: this operation will update the size of the 2 tables used below
            # dot1qVlanStaticEgressPorts & dot1qVlanStaticUntaggedPorts
            if not vlan_id in existing_vlans:
                print '-> new vlan, creating it...'
                self.snmp.dot1qVlanStaticRowStatus[vlan_id] = Q_BRIDGE_MIB_CreateAndGo
                existing_vlans[vlan_id] = { 'preconfigured': False,
                                            'name': '' }
            if existing_vlans[vlan_id]['preconfigured']:
                print '-> bypassing vlan name update (this vlan was preconfigured in the device)'
            else:
                new_vlan_name = config.registered_vlans[vlan_id]
                old_name = existing_vlans[vlan_id]['name']
                if old_name != new_vlan_name:
                    print '-> setting vlan name to', new_vlan_name, '(was %s)' % old_name
                    self.snmp.dot1qVlanStaticName[vlan_id] = new_vlan_name
            print '-> retrieving current config egress / untagged ports'
            egress_ports = PortsBitField(self.snmp.dot1qVlanStaticEgressPorts[vlan_id])
            untagged_ports = PortsBitField(self.snmp.dot1qVlanStaticUntaggedPorts[vlan_id])
            print '-> applying changes'
            for port_config in config.port_configs:
                egress = 1 if vlan_id in port_config.egress_vlans else 0
                untag = 1 if vlan_id in port_config.untagged_vlans else 0
                egress_ports[port_config.port] = egress
                untagged_ports[port_config.port] = untag
            print '-> saving egress / untagged ports config on device'
            self.snmp.dot1qVlanStaticEgressPorts[vlan_id] = egress_ports.toOctetString()
            self.snmp.dot1qVlanStaticUntaggedPorts[vlan_id] = untagged_ports.toOctetString()

