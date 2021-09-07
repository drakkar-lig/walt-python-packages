from time import time
from collections import defaultdict
from walt.common.formatting import format_sentence_about_nodes
from walt.server.threads.main.nodes.netservice import node_request

POE_REBOOT_DELAY            = 2  # seconds

def run_next_step(next_steps, **env):
    step = next_steps[0]
    step(next_steps = next_steps[1:], **env)

def reboot_nodes(nodes, **env):
    # prepare work
    env.update(
        remaining_nodes = list(nodes),
        next_steps = [  reboot_virtual_nodes,
                        soft_reboot_nodes,
                        hard_reboot_nodes,
                        reply_requester ]
    )
    # start process
    run_next_step(**env)

def reboot_virtual_nodes(nodes_manager, remaining_nodes, **env):
    # check for virtual vs physical nodes
    # and hard reboot vnodes by killing their VM
    vmrebooted = []
    for node in remaining_nodes.copy():
        if node.virtual:
            # restart VM (this will restart the node if running)
            nodes_manager.start_vnode(node)
            # move node to 'vmrebooted' category
            remaining_nodes.remove(node)
            vmrebooted.append(node.name)
    env.update(nodes_manager = nodes_manager,
               remaining_nodes = remaining_nodes,
               vmrebooted = vmrebooted)
    run_next_step(**env)

def soft_reboot_nodes(**env):
    if env['hard_only'] or len(env['remaining_nodes']) == 0:
        run_next_step(softrebooted = [], softreboot_errors = {}, **env)
    else:
        # try to softreboot remaining_nodes
        node_request(env['ev_loop'], env['remaining_nodes'], 'REBOOT', softreboot_callback, env)

def softreboot_callback(results, remaining_nodes, **env):
    softrebooted = []
    softreboot_errors = {}
    for result_msg, nodes in results.items():
        if result_msg == 'OK':
            for node in nodes:
                remaining_nodes.remove(node)
                softrebooted.append(node.name)
        else:
            for node in nodes:
                softreboot_errors[node.name] = result_msg.lower()
    env.update(remaining_nodes = remaining_nodes,
               softrebooted = softrebooted,
               softreboot_errors = softreboot_errors)
    run_next_step(**env)

def hard_reboot_nodes(requester, remaining_nodes, **env):
    if len(remaining_nodes) > 0:
        if requester.has_hook('client_hard_reboot'):
            hard_reboot_method_name = \
                requester.get_hard_reboot_method_name()
            hard_reboot_steps = [
                        client_hard_reboot
            ]
        else:
            hard_reboot_method_name = 'PoE-reboot'
            hard_reboot_steps = [
                        filter_poe_rebootable,
                        poe_reboot
            ]
        next_steps = hard_reboot_steps + env['next_steps']
        env.update(
            requester = requester,
            remaining_nodes = remaining_nodes,
            hard_reboot_method_name = hard_reboot_method_name,
            next_steps = next_steps
        )
    else:
        env.update(
            requester = requester,
            remaining_nodes = remaining_nodes,
            hardrebooted = [],
            hardreboot_errors = {},
            hard_reboot_method_name = 'none'
        )
    run_next_step(**env)

def client_hard_reboot(requester, remaining_nodes, **env):
    mac_to_nodes = { node.mac: node for node in remaining_nodes }
    node_macs = tuple(mac_to_nodes.keys())
    mac_hardrebooted, mac_hardreboot_errors = \
            requester.hard_reboot_nodes(node_macs)
    env.update(
        requester = requester,
        hardrebooted = [
            mac_to_nodes[mac] for mac in mac_hardrebooted
        ],
        hardreboot_errors = {
            mac_to_nodes[mac].name: error \
            for mac, error in mac_hardreboot_errors.items()
        }
    )
    run_next_step(**env)

def filter_poe_rebootable(nodes_manager, remaining_nodes, **env):
    hardreboot_errors = {}
    for node in remaining_nodes.copy():
        sw_info, sw_port = nodes_manager.topology.get_connectivity_info( \
                                node.mac)
        if sw_info:
            if sw_info.conf.get('poe.reboots', False) == True:
                pass # ok, allowed
            else:
                hardreboot_errors[node.name] = 'forbidden on switch'
                remaining_nodes.remove(node)
        else:
            hardreboot_errors[node.name] = 'unknown LLDP network position'
            remaining_nodes.remove(node)
    env.update(nodes_manager = nodes_manager,
               hardreboot_errors = hardreboot_errors,
               remaining_nodes = remaining_nodes)
    run_next_step(**env)

def poe_reboot(remaining_nodes, hardreboot_errors, **env):
    if len(remaining_nodes) == 0:
        # nothing to do here
        run_next_step(  hardrebooted = [],
                        hardreboot_errors = hardreboot_errors,
                        **env)
        return
    # define callback functions
    def cb_poweroff():
        env['blocking'].nodes_set_poe(env['requester'], cb_after_poweroff, poerebootable, False)
    def cb_after_poweroff(poweroff_result):
        powered_off, in_hardreboot_errors = poweroff_result
        hardreboot_errors.update(**in_hardreboot_errors)
        timeout_at = time() + POE_REBOOT_DELAY
        env['ev_loop'].plan_event(
            ts = timeout_at,
            callback = cb_poweron,
            powered_off = powered_off
        )
    def cb_poweron(powered_off):
        env['blocking'].nodes_set_poe(env['requester'], cb_after_poweron, powered_off, True)
    def cb_after_poweron(poweron_result):
        powered_on, in_hardreboot_errors = poweron_result
        hardreboot_errors.update(**in_hardreboot_errors)
        env.update(
            hardrebooted = [n['name'] for n in powered_on],
            hardreboot_errors = hardreboot_errors
        )
        run_next_step(**env)
    # make nodes pickle-able
    poerebootable = [n._asdict() for n in remaining_nodes]
    # start poe reboot process
    cb_poweroff()

def reply_requester(requester, task_callback, hard_only,
            vmrebooted, softrebooted, hardrebooted,
            softreboot_errors, hardreboot_errors,
            hard_reboot_method_name, **env):
    if len(hardreboot_errors) == 0:
        # we managed to reboot all nodes, so we can be brief.
        requester.stdout.write('Done.\n')
    else:
        # not all went well
        rebooted = tuple(vmrebooted) + tuple(softrebooted) + tuple(hardrebooted)
        if len(rebooted) > 0:
            requester.stdout.write(format_sentence_about_nodes(
                '%s: OK.\n', rebooted))
        per_errors = defaultdict(list)
        for node_name in hardreboot_errors:
            errors = (hardreboot_errors[node_name],)
            if not hard_only:   # then soft reboot was tried too
                errors += (softreboot_errors[node_name],)
            per_errors[errors].append(node_name)
        for errors, node_names in per_errors.items():
            if hard_only:   # no soft reboot error, just a poe reboot error
                hard_error = errors[0]
                explain = 'failed %s (%s)' % (hard_reboot_method_name, hard_error)
            else:
                hard_error, soft_error = errors
                explain = 'failed soft-reboot (%s) and %s (%s)' % \
                            (soft_error, hard_reboot_method_name, hard_error)
            requester.stderr.write(format_sentence_about_nodes(
                    '%s: ' + explain + '\n', node_names))
        if not hard_only:   # then we had soft reboot errors
            requester.stdout.write('note: soft-reboot only works when node is fully booted.\n')
    # unblock client
    task_callback(None)
