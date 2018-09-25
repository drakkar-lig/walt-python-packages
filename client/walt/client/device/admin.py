from collections import OrderedDict
from walt.common.tools import serialize_ordered_dict, deserialize_ordered_dict
from walt.client.link import ClientToServerLink
from walt.client.tools import yes_or_no, choose, confirm
from walt.client.application import WalTApplication

MSG_NOT_APPLICABLE = """\
%(device_name)s is a %(device_type)s.
'walt device admin' is only applicable to switches and \
unknown devices."""

MSG_EXPLAIN_LLDP_EXPLORE = """\
If you allow it, WalT may send SNMP requests to this switch in
order to list its LLDP (Link-Layer Discovery Protocol) neighbors.
If this is disabled, equipment linked to this switch will not be
detected, and we will not be able to use PoE to hard-reboot the
nodes connected there.
"""

MSG_EXPLAIN_POE_REBOOT = """\
Sometimes WalT may send SNMP requests to a switch in order to
hard-reboot the nodes connected there.
This is done by turning PoE (Power-Over-Ethernet) off and back on
on the appropriate switch port.
In case this is disabled, if ever some nodes become unresponsive
and soft-reboot fails, you might need to unplug & replug those
nodes manually.
"""

MSG_QUESTION_ALLOW_POE_REBOOT = """\
Is WalT allowed to temporarily disable PoE on its ports?"""

MSG_INDICATE_SNMP_VERSION = """\
Please indicate the version WalT should use to query this switch."""

MSG_UNKNOWN_MANAGEMENT_IP = """\
Management IP of this switch is unknown. Please specify it:"""

def ask_switch_conf(device_info):
    conf = OrderedDict()
    print 'Starting switch setup'
    print '---------------------'
    conf['allow_lldp_explore'] = False
    conf['allow_poe_reboot'] = None
    conf['snmp'] = None
    conf['ip'] = device_info['ip']
    if conf['ip'] is None:
        print MSG_UNKNOWN_MANAGEMENT_IP,
        conf['ip'] = raw_input()
        print 'OK.\n'
    print MSG_EXPLAIN_LLDP_EXPLORE
    if yes_or_no('Is WalT allowed to explore LLDP neighbors of this switch?'):
        conf['allow_lldp_explore'] = True
        conf['allow_poe_reboot'] = False
        print MSG_EXPLAIN_POE_REBOOT
        if yes_or_no('Is this switch PoE-capable?'):
            if yes_or_no(MSG_QUESTION_ALLOW_POE_REBOOT):
                conf['allow_poe_reboot'] = True
        # we need SNMP configuration
        snmp_conf = ask_snmp_conf()
        conf['snmp'] = snmp_conf
    else:
        # if LLDP is not allowed, then we don't know where nodes are
        # connected, thus we cannot use PoE to hard-reboot them, and
        # the PoE-related questions are no more meaningful.
        pass
    # confirm
    print 'Please review the following setup:'
    print '----------------------------------'
    print
    display_conf(conf)
    print
    if confirm('Is it OK?'):
        return conf
    else:
        return None

def ask_snmp_conf():
    print 'Starting SNMP setup'
    print '-------------------'
    possible_values = {
        '1': 'SNMP version 1',
        '2': 'SNMP version 2' }
    version = choose(MSG_INDICATE_SNMP_VERSION, **possible_values)
    print 'OK.\n'
    print 'Please indicate the community string WalT should use:',
    community = raw_input()
    print 'OK.\n'
    return OrderedDict(
        version = int(version),
        community = community
    )

def display_conf(conf, prefix = ''):
    for k, v in conf.items():
        if isinstance(v, OrderedDict):
            print '%s%s:' % (prefix, k)
            display_conf(v, prefix + '  ')
        elif v == None:
            continue
        else:
            print '%s%s: %s' % (prefix, k, str(v))

class WalTDeviceAdmin(WalTApplication):
    """configure WalT regarding network switches and unknown devices"""
    def main(self, device_name):
        with ClientToServerLink() as server:
            device_info = server.get_device_info(device_name)
            device_info = deserialize_ordered_dict(device_info)
            device_type = device_info['type']
            if not device_type:
                return  # issue already reported
            if device_type not in ('unknown', 'switch'):
                print MSG_NOT_APPLICABLE % dict(
                    device_name = device_name,
                    device_type = device_type
                )
                return
            if device_type == 'unknown':
                print 'WalT could not autodetect the type of this device.\n'
                if yes_or_no('Is it a network switch?', komsg = 'Nothing to do.'):
                    device_type = 'switch'
            if device_type == 'switch':
                conf = ask_switch_conf(device_info)
                if conf == None:
                    return
                conf = serialize_ordered_dict(conf)
                server.apply_switch_conf(device_name, conf)

