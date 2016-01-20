#!/usr/bin/env python
from walt.server.snmp.vlan import PortConfig, SwitchConfig

def configure_main_switch_if_needed(snmp_proxy):
    if snmp_proxy.vlan.vlan_exists('walt-out'):
        print 'the main switch is already configured'
        return False    # already configured
    else:
        print 'configuring the main switch...'
        config = SwitchConfig()
        config.register_vlan(1, 'walt')
        config.register_vlan(169, 'walt-out')
        config.add_port_config(PortConfig(1).access(169))
        config.add_port_config(PortConfig(2).trunk([1,169]))
        # other ports keep their default config (access mode, vlan 1)
        snmp_proxy.vlan.apply_config_to_device(config)
        return True


