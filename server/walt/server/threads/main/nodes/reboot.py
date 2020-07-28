from time import time
from collections import defaultdict
from walt.common.tools import format_sentence_about_nodes
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
                        filter_poe_rebootable,
                        poe_reboot,
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
            # terminate VM by quitting screen session
            nodes_manager.try_kill_vnode(node.name)
            # restart VM
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

def filter_poe_rebootable(nodes_manager, remaining_nodes, **env):
    poereboot_errors = {}
    for node in remaining_nodes.copy():
        sw_info, sw_port = nodes_manager.topology.get_connectivity_info( \
                                node.mac)
        if sw_info:
            if sw_info.conf.get('poe.reboots', False) == True:
                pass # ok, allowed
            else:
                poereboot_errors[node.name] = 'forbidden on switch'
                remaining_nodes.remove(node)
        else:
            poereboot_errors[node.name] = 'unknown LLDP network position'
            remaining_nodes.remove(node)
    env.update(nodes_manager = nodes_manager,
               poereboot_errors = poereboot_errors,
               remaining_nodes = remaining_nodes)
    run_next_step(**env)

def poe_reboot(remaining_nodes, poereboot_errors, **env):
    if len(remaining_nodes) == 0:
        # nothing to do here
        run_next_step(  poerebooted = [],
                        poereboot_errors = poereboot_errors,
                        **env)
        return
    # define callback functions
    def cb_poweroff():
        env['blocking'].nodes_set_poe(env['requester'], cb_after_poweroff, poerebootable, False)
    def cb_after_poweroff(poweroff_result):
        powered_off, in_poereboot_errors = poweroff_result
        poereboot_errors.update(**in_poereboot_errors)
        timeout_at = time() + POE_REBOOT_DELAY
        env['ev_loop'].plan_event(
            ts = timeout_at,
            callback = cb_poweron,
            powered_off = powered_off
        )
    def cb_poweron(powered_off):
        env['blocking'].nodes_set_poe(env['requester'], cb_after_poweron, powered_off, True)
    def cb_after_poweron(poweron_result):
        powered_on, in_poereboot_errors = poweron_result
        poereboot_errors.update(**in_poereboot_errors)
        env.update(
            poerebooted = [n['name'] for n in powered_on],
            poereboot_errors = poereboot_errors
        )
        run_next_step(**env)
    # make nodes pickle-able
    poerebootable = [n._asdict() for n in remaining_nodes]
    # start poe reboot process
    cb_poweroff()

def reply_requester(requester, task_callback, hard_only,
            vmrebooted, softrebooted, poerebooted,
            softreboot_errors, poereboot_errors, **env):
    if len(poereboot_errors) == 0:
        # we managed to reboot all nodes, so we can be brief.
        requester.stdout.write('Done.\n')
    else:
        # not all went well
        rebooted = tuple(vmrebooted) + tuple(softrebooted) + tuple(poerebooted)
        if len(rebooted) > 0:
            requester.stdout.write(format_sentence_about_nodes(
                '%s: OK.\n', rebooted))
        per_errors = defaultdict(list)
        for node_name in poereboot_errors:
            errors = (poereboot_errors[node_name],)
            if not hard_only:   # then soft reboot was tried too
                errors += (softreboot_errors[node_name],)
            per_errors[errors].append(node_name)
        for errors, node_names in per_errors.items():
            if hard_only:   # no soft reboot error, just a poe reboot error
                poe_error = errors[0]
                explain = 'failed PoE-reboot (%s)' % poe_error
            else:
                poe_error, soft_error = errors
                explain = 'failed soft-reboot (%s) and PoE-reboot (%s)' % \
                            (soft_error, poe_error)
            requester.stderr.write(format_sentence_about_nodes(
                    '%s: ' + explain + '\n', node_names))
        if not hard_only:   # then we had soft reboot errors
            requester.stdout.write('note: soft-reboot only works when node is fully booted.\n')
    # unblock client
    task_callback(None)
