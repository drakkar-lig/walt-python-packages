#!/usr/bin/env python
import time, snimpy
from walt.server import snmp, status, network
from waltvlanconf import configure_main_switch_if_needed

def main_switch_conf_callback(local_ip, switch_ip):
    print 'with %s we can reach the switch' % local_ip
    status.update('ensuring proper vlan configuration of the main switch...')
    configured = configure_main_switch_if_needed(
                        snmp.Proxy(str(switch_ip), vlan=True))
    return configured

def setup_needed():
    # check if an ip was already assigned, which 
    # shows that setup was already done
    while True:
        try:
            snmp_local = snmp.Proxy('localhost', lldp=True)
            if len(snmp_local.lldp.get_local_ips()) > 0:
                return False    # setup already done
            else:
                return True     # setup needed
        except snimpy.snmp.SNMPNoSuchObject:
            print 'Not ready, waiting...'
            time.sleep(1)
        else:
            break

def setup():
    # unable connectivity for walt client to be able
    # to get our status through snmp 
    network.tools.dhcp_start(['eth0', 'eth0.169'])
    status.update('detecting the main switch...')
    # retrieve info about the main switch by
    # using the local lldp & snmp daemons
    snmp_local = snmp.Proxy('localhost', lldp=True)
    while len(snmp_local.lldp.get_neighbors()) == 0:
        time.sleep(0.5)
    main_switch_info = snmp_local.lldp.get_neighbors().values()[0]
    print 'main switch:', main_switch_info
    # assign a temporary ip in order to communicate
    # with the main switch, and, if not done yet, set up
    # its vlan configuration
    status.update('detecting parameters for communication with the main switch...')
    switch_ip = network.tools.ip(main_switch_info['ip'])
    reached, configured = network.tools.assign_temp_ip_to_reach_neighbor(
                                switch_ip,
                                main_switch_conf_callback)
    if reached == False:
        status.update('ERROR: unable to communicate with the main switch (try to reset it to factory settings).')
        return False    # not ok
    # set up the server ip on eth0 (walt testbed network)
    # and restart the dhcp client on eth0.169 only (walt-out vlan)
    network.tools.dhcp_stop()
    network.tools.set_server_ip()
    network.tools.dhcp_start(['eth0.169'])
    return True     # ok

