#!/usr/bin/env python
# coding=utf-8
import time, snimpy
from walt.server.const import SERVER_SNMP_CONF
from walt.server.threads.main.mydocker import DockerClient
from walt.server.threads.main import snmp
from walt.server.threads.main.network.tools import lldp_update

MSG_WAITING_COMPANION_SERVICES = 'Waiting for companion services to be ready...'
MSG_DETECTING_MAIN_SWITCH = 'Detecting the main switch...'
MSG_CHECK_DOCKER = "Checking internet connection to the Docker Hub..."

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

ACTION_CHECK_DOCKER = u'''
The server failed to access hub.docker.com. Please verify that the server is allowed to reach internet.
The setup process will retry this periodically until it succeeds.
'''

def wait_companion_services(ui):
    ui.task_start(MSG_WAITING_COMPANION_SERVICES)
    while True:
        try:
            snmp_local = snmp.Proxy('localhost', SERVER_SNMP_CONF, lldp=True)
            print snmp_local.lldp.get_local_ips()
        except snimpy.snmp.SNMPException:
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
    #check_docker(ui)
    wait_companion_services(ui)
    #wait_for_main_switch(ui, MSG_DETECTING_MAIN_SWITCH)

def wait_for_main_switch(ui, msg, explain = None, todo = None):
    ui.task_start(msg, explain=explain, todo=todo)
    # retrieve info about the main switch by
    # using the local lldp & snmp daemons
    snmp_local = snmp.Proxy('localhost', SERVER_SNMP_CONF, lldp=True)
    while True:
        try:
            neighbors = snmp_local.lldp.get_neighbors().values()
        except SNMPException:
            neighbors = []
        if len(neighbors) > 0:
            break
        ui.task_running()
        lldp_update()
        time.sleep(1)
    ui.task_done()
    main_switch_info = neighbors[0]
    print 'main switch:', main_switch_info
    return main_switch_info

