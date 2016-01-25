#!/usr/bin/env python
# coding=utf-8
import time, snimpy, sys, os
from walt.server import snmp, status, network
from walt.server.network.tools import lldp_update
from waltvlanconf import configure_main_switch_if_needed
from walt.common.tools import do
from walt.server.mydocker import DockerClient
from walt.server.const import WALT_INTF, SETUP_INTF, EXTERN_INTF

PLATFORM_READY_FILE = '/var/lib/walt/platform_ready'
MSG_WAITING_COMPANION_SERVICES = 'Waiting for companion services to be ready...'
MSG_DETECTING_MAIN_SWITCH = 'Detecting the main switch...'
MSG_AUTO_CONFIGURING_MAIN_SWITCH = 'Auto-configuring the main switch...'
MSG_ERROR_RESET_THE_SWITCH_REBOOT = '''\
Could not communicate with the main switch. Try to reset it to factory settings.
The server will reboot and retry this bootup procedure in a few seconds.
'''
MSG_DHCP_REQUEST = "Waiting for internet connection..."
MSG_CHECK_DOCKER = "Checking internet connection to the Docker Hub..."
MSG_WAITING_USER = "Waiting for user action..."

EXPLAIN_PLUG_SERVER = u'''\
We will first connect the WalT server and the main switch:

┌────────────────┐
│main switch     │
│1 2 [3-and-more]│
└┼─┼─┼─┼─┼─┼─┼─┼─┘
   │
   │
   └ walt server
'''

EXPLAIN_PLUG_ELEMENTS = u'''\
We will now connect the other elements of the WalT platform: cascaded switches and nodes.

┌────────────────┐      ┌─────────────┐
│main switch     │      │switch2      │
│1 2 [3-and-more]│      │[any port...]│
└┼─┼─┼─┼─┼─┼─┼─┼─┘      └┼─┼─┼─┼─┼─┼─┼┘
   │       │ └─────────────┘   │ └ node_Y
   │       └ node_X            └ node_Z
   └ walt server

You can use ports 3 and more of the main switch, and any port of the other switches
to connect these elements together.
Once a given switch is connected, power if off and on in order to ensure that its internal
network configuration is reset.
'''

EXPLAIN_PLUG_INTERNET_CABLE = u'''\
The cable to the external VLAN should now be plugged on port 1 of the main switch:

┌────────────────┐      ┌─────────────┐
│main switch     │      │switch2      │
│1 2 [3-and-more]│      │[any port...]│
└┼─┼─┼─┼─┼─┼─┼─┼─┘      └┼─┼─┼─┼─┼─┼─┼┘
 │ │       │ └─────────────┘   │ └ node_Y
 │ │       └ node_X            └ node_Z
 │ └ walt server
 └ to internet

This external VLAN is expected to provide a DHCP service and internet access (at least to the docker hub).
'''

ACTION_PLUG_SERVER = u'''
Please plug the WalT server to port number 2 of one of the switches (and power this switch on).
Do not plug anything more for now.
The procedure will continue when this switch is detected (this may take a few minutes even if it is already connected).
'''

ACTION_PLUG_ELEMENTS = u'''
Please plug the other switches and nodes as described above.
Press <Enter> when ready.
'''

ACTION_PLUG_INTERNET_CABLE = u'''
Please plug the cable of the external VLAN to port 1 of the main switch.
The server (mac address %(mac)s) will now be sending DHCP requests on this externally managed VLAN.
The setup process will continue when a DHCP offer is obtained.
'''

ACTION_CHECK_DOCKER = u'''
The server failed to access hub.docker.com. Please verify that the server is allowed to reach internet.
The setup process will retry this periodically until it succeeds.
'''

def main_switch_conf_callback(local_ip, switch_ip, intf, ui):
    ui.task_running()
    configured = configure_main_switch_if_needed(
                        snmp.Proxy(str(switch_ip), vlan=True))
    return configured

def wait_companion_services(ui):
    ui.task_start(MSG_WAITING_COMPANION_SERVICES)
    server_ip = str(network.tools.get_server_ip())
    while True:
        try:
            snmp_local = snmp.Proxy('localhost', lldp=True)
            print snmp_local.lldp.get_local_ips()
        except snimpy.snmp.SNMPNoSuchObject:
            ui.task_running()
            time.sleep(1)
        else:
            break
    ui.task_done()

def check_docker(ui):
    ui.task_start(  MSG_CHECK_DOCKER,
                    explain=EXPLAIN_PLUG_INTERNET_CABLE,
                    todo=ACTION_CHECK_DOCKER)
    docker = DockerClient()
    while not docker.self_test():
        ui.task_running()
        time.sleep(1)
    ui.task_done()

def setup(ui):
    wait_companion_services(ui)
    if not os.path.exists(PLATFORM_READY_FILE):
        setup_platform(ui)
        # create the file
        with open(PLATFORM_READY_FILE, 'a'):
            pass
    else:
        init_after_system_restart(ui)

def init_after_system_restart(ui):
    main_switch_info = wait_for_main_switch(ui, MSG_DETECTING_MAIN_SWITCH)
    network.tools.dhcp_wait_ip(EXTERN_INTF, ui, MSG_DHCP_REQUEST)

def wait_for_main_switch(ui, msg, explain = None, todo = None):
    ui.task_start(msg, explain=explain, todo=todo)
    # retrieve info about the main switch by
    # using the local lldp & snmp daemons
    snmp_local = snmp.Proxy('localhost', lldp=True)
    while len(snmp_local.lldp.get_neighbors()) == 0:
        ui.task_running()
        lldp_update()
        time.sleep(1)
    ui.task_done()
    main_switch_info = snmp_local.lldp.get_neighbors().values()[0]
    print 'main switch:', main_switch_info
    return main_switch_info

def auto_configure_main_switch(ui, switch_ip):
    ui.task_start(MSG_AUTO_CONFIGURING_MAIN_SWITCH)
    reached = False
    # assign a temporary ip in order to communicate
    # with the main switch, and set up its vlan configuration
    ui.task_running()
    reached, configured = network.tools.assign_temp_ip_to_reach_neighbor(
                                switch_ip,
                                main_switch_conf_callback,
                                SETUP_INTF,
                                ui)
    if not reached:
        ui.task_failed(MSG_ERROR_RESET_THE_SWITCH_REBOOT)
        time.sleep(10)
        do('reboot')
        time.sleep(10)
        sys.exit()
    ui.task_done()

def wait_other_elements_plugged(ui):
    ui.task_start(MSG_WAITING_USER, explain=EXPLAIN_PLUG_ELEMENTS,
                todo=ACTION_PLUG_ELEMENTS)
    ui.task_running(activity_sign = False)
    ui.wait_user_keypress()
    ui.task_done()

def setup_platform(ui):
    main_switch_info = wait_for_main_switch(
                    ui,
                    MSG_DETECTING_MAIN_SWITCH,
                    explain=EXPLAIN_PLUG_SERVER,
                    todo=ACTION_PLUG_SERVER)
    switch_ip = network.tools.ip(main_switch_info['ip'])
    auto_configure_main_switch(ui, switch_ip)
    wait_other_elements_plugged(ui)
    # get a server ip on eth0.169 (external VLAN) using DHCP
    mac_addr = network.tools.get_mac_address(EXTERN_INTF)
    network.tools.dhcp_wait_ip(
                EXTERN_INTF,
                ui,
                MSG_DHCP_REQUEST,
                EXPLAIN_PLUG_INTERNET_CABLE,
                ACTION_PLUG_INTERNET_CABLE % dict(mac = mac_addr))
    # check connection to the docker hub
    check_docker(ui)

