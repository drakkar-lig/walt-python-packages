#!/usr/bin/env python
import select, subprocess, shlex
from ipaddress import ip_address, ip_network
from walt.common.tools import do, succeeds
from walt.server import const

def ip(ip_as_str):
    return ip_address(unicode(ip_as_str))

def net(net_as_str):
    return ip_network(unicode(net_as_str))

def find_free_ip_near(ip, intf, increment):
    target_ip = ip
    while True:
        target_ip += increment
        if succeeds('arping -D -w 1 -I %s %s' % (intf, target_ip)):
            return target_ip

def smallest_subnet_for_these_ip_addresses(ip1, ip2):
    # start with <ip1>/31, then <ip1>/30 etc.
    # until <ip2> is in this network too.
    for netrange in range(31,0,-1):
        net = ip_network(u'%s/%d' % (ip1, netrange), strict=False)
        if ip2 in net:
            return net

def get_mac_address(intf):
    with open('/sys/class/net/' + intf +'/address') as f:
        return f.read().strip()

def dhcp_wait_ip(intf, ui, msg, explain):
    # dhclient will go to background when an IP is obtained,
    # which should release the popen process.
    ui.task_start(msg, explain=explain)
    cmd = 'dhclient -1 %s' % intf
    while True:
        dh_client = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
        poller = select.poll()
        poller.register(dh_client.stdout, select.POLLIN)
        while len(poller.poll(500)) == 0:   # timeout unit is milliseconds
            ui.task_running()
        poller.unregister(dh_client.stdout)
        # check the return code, if not 0 loop again
        dh_client.wait()
        if dh_client.returncode == 0:
            break
    ui.task_done()

def dhcp_stop():
    do('dhclient -r')

def add_ip_to_interface(ip, subnet, intf):
    do('ip addr add %s/%d dev %s' % (ip, subnet.prefixlen, intf))

def del_ip_from_interface(ip, subnet, intf):
    do('ip addr del %s/%d dev %s' % (ip, subnet.prefixlen, intf))

def check_if_we_can_reach(remote_ip):
    return succeeds('ping -c 1 -w 1 %s' % remote_ip)

def assign_temp_ip_to_reach_neighbor(neighbor_ip, callback, *args):
    reached = False
    callback_result = None
    for increment in [ 1, -1 ]:
        free_ip = find_free_ip_near(neighbor_ip, 'eth0', increment)
        subnet = smallest_subnet_for_these_ip_addresses(neighbor_ip, free_ip)
        add_ip_to_interface(free_ip, subnet, 'eth0')
        if check_if_we_can_reach(neighbor_ip):
            callback_result = callback(free_ip, neighbor_ip, *args)
            reached = True
        del_ip_from_interface(free_ip, subnet, 'eth0')
        if reached:
            break
    return (reached, callback_result)

def lldp_update():
    do('lldpcli update')

def get_server_ip():
    subnet = net(const.WALT_SUBNET)
    return list(subnet.hosts()).pop(0)

def set_server_ip():
    add_ip_to_interface(
            get_server_ip(),
            net(const.WALT_SUBNET),
            'eth0')
    # let neighbors know we have updated things
    lldp_update()

def ip_in_walt_network(input_ip):
    subnet = net(const.WALT_SUBNET)
    return ip(input_ip) in subnet

