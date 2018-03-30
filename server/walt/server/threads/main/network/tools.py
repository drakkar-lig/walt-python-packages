#!/usr/bin/env python
import select, subprocess, shlex
from ipaddress import ip_address, ip_network
from walt.common.tools import do, succeeds
from walt.server import const, conf
from walt.server.threads.main.snmp import Proxy

def ip(ip_as_str):
    return ip_address(unicode(ip_as_str))

def net(net_as_str):
    return ip_network(unicode(net_as_str), strict=False)

def get_walt_subnet():
    return net(conf['network']['walt-net']['ip'])

def get_walt_adm_subnet():
    walt_adm_conf = conf['network'].get('walt-adm', None)
    if walt_adm_conf is None:
        return None
    else:
        return net(walt_adm_conf['ip'])

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

def add_ip_to_interface(ip, subnet, intf):
    do('ip addr add %s/%d dev %s' % (ip, subnet.prefixlen, intf))

def del_ip_from_interface(ip, subnet, intf):
    do('ip addr del %s/%d dev %s' % (ip, subnet.prefixlen, intf))

def check_if_we_can_reach(remote_ip):
    return succeeds('ping -c 1 -w 1 %s' % remote_ip)

def is_walt_address(ip):
    return ip in get_walt_subnet()

def assign_temp_ip_to_reach_neighbor(neighbor_ip, callback, intf, *args):
    reached = False
    callback_result = None
    for increment in [ 1, -1 ]:
        free_ip = find_free_ip_near(neighbor_ip, intf, increment)
        subnet = smallest_subnet_for_these_ip_addresses(neighbor_ip, free_ip)
        print free_ip, subnet
        add_ip_to_interface(free_ip, subnet, intf)
        if check_if_we_can_reach(neighbor_ip):
            callback_result = callback(free_ip, neighbor_ip, intf, *args)
            reached = True
        del_ip_from_interface(free_ip, subnet, intf)
        if reached:
            break
    return (reached, callback_result)

def set_static_ip_on_switch(switch_ip, snmp_conf):
    p = Proxy(switch_ip, snmp_conf, ipsetup=True)
    p.ipsetup.record_current_ip_config_as_static()

def lldp_update():
    do('lldpcli update')

def get_server_ip():
    return conf['network']['walt-net']['ip'].split('/')[0]

def ip_in_walt_network(input_ip):
    subnet = get_walt_subnet()
    return ip(input_ip) in subnet

def ip_in_walt_adm_network(input_ip):
    subnet = get_walt_adm_subnet()
    if subnet is None:
        return False
    else:
        return ip(input_ip) in subnet

def get_dns_servers():
    local_server_is_dns_server = False
    dns_list = []
    with open('/etc/resolv.conf', 'r') as f:
        for line in f:
            line = line.strip()
            if line[0] == '#':
                continue
            if line.startswith('nameserver'):
                for dns_ip in line.split(' ')[1:]:
                    if dns_ip.startswith('127.'):
                        local_server_is_dns_server = True
                        continue
                    dns_list.append(dns_ip)
    # If walt server is a DNS server, and no other DNS is available, let the
    # walt nodes use it (but not with its localhost address!)
    if local_server_is_dns_server and len(dns_list) == 0:
        dns_list.append(get_server_ip())
    # Still no DNS server...  Hope that this one is reachable
    if len(dns_list) == 0:
        dns_list.append('8.8.8.8')
    return dns_list
