from collections import defaultdict
from time import time

from walt.common.formatting import format_sentence_about_nodes
from walt.server.processes.main.nodes.netservice import node_request
from walt.server.processes.main.workflow import Workflow

# kev
from walt.server.processes.main.nodes.wakeonlan import Waker
from walt.server.tools import get_walt_subnet

POE_REBOOT_DELAY = 2  # seconds
WOL_REBOOT_DELAY = 3


def reboot_nodes(nodes, powersave, hard_only, **env):
    # notify the powersave module we are working on these nodes
    powersave.handle_event("reboot", nodes)
    # prepare work
    env.update(remaining_nodes=list(nodes))
    env.update(powersave=powersave, hard_only=hard_only)
    if hard_only:
        env.update(softrebooted=[], softreboot_errors=[])
        wf = Workflow(
            [
                wf_hard_reboot_virtual_nodes,
                wf_hard_reboot_nodes_poe,
                wf_hard_reboot_nodes_wol,
                wf_reply_requester,
            ],
            **env
        )
        # start process
        wf.run()
    else: 
        # WoL implies soft-reboot, so if soft-reboot fails
        # don't try hard_reboot_WoL it would fails too
        wf = Workflow(
            [
                # wake up directly  powersave off nodes
                wf_wakeup_poe,
                wf_wakeup_wol,
                # then do classic steps for a soft reboot
                wf_soft_reboot_nodes,
                wf_hard_reboot_virtual_nodes,
                wf_hard_reboot_nodes_poe,
                wf_reply_requester,
            ],
            **env
        )
        # start process
        wf.run()

def wf_wakeup_wol(wf, ev_loop, db, nodes_manager, hard_only, remaining_nodes,
                         reboot_cause, **env):
    off_macs = db.get_wol_off_macs()
    already_off = []
    for node in remaining_nodes:
        if node.mac in off_macs:
            already_off.append(node)
            remaining_nodes.remove(node)
    wf.insert_steps([wf_wol_on])
    wf.update_env(remaining_nodes=remaining_nodes,
                  powered_off=already_off,
                  hardreboot_errors={})
    wf.next()

def wf_wakeup_poe(wf, ev_loop, db, nodes_manager, hard_only, remaining_nodes,
                         reboot_cause, **env):
    off_macs = db.get_poe_off_macs()
    already_off = []
    for node in remaining_nodes:
        if node.mac in off_macs:
            already_off.append(node)
            remaining_nodes.remove(node)
    
    wf.update_env(already_off=already_off, powered_off=[], hardreboot_errors={})
    wf.insert_steps([wf_poe_poweron, wf_poe_after_poweron])
    wf.next()

def wf_hard_reboot_virtual_nodes(wf, nodes_manager, remaining_nodes, reboot_cause,
                                 **env):
    # check for virtual vs physical nodes
    # and hard reboot vnodes by killing their VM
    vmrebooted = []
    for node in remaining_nodes.copy():
        if node.virtual:
            # restart VM
            nodes_manager.vnode_hard_reboot(node.mac)
            nodes_manager.change_nodes_bootup_status(
                    nodes=[node], booted=False,
                    cause=reboot_cause, method="vnode hard-reboot")
            # move node to 'vmrebooted' category
            remaining_nodes.remove(node)
            vmrebooted.append(node.name)
    wf.update_env(vmrebooted=vmrebooted)
    wf.next()


def wf_soft_reboot_nodes(wf, ev_loop, db, nodes_manager, hard_only, remaining_nodes,
                         reboot_cause, **env):
    # do not try a softreboot for nodes with PoE off
    off_macs = db.get_poe_off_macs() + \
                db.get_wol_off_macs() # and WoL off
    softrebootable_nodes = list(n for n in remaining_nodes if n.mac not in off_macs)
    node_request(
        ev_loop,
        softrebootable_nodes,
        "REBOOT",
        wf_softreboot_callback,
        dict(remaining_nodes=remaining_nodes, wf=wf,
                nodes_manager=nodes_manager, reboot_cause=reboot_cause),
    )


def wf_softreboot_callback(results, wf, remaining_nodes, nodes_manager, reboot_cause):
    softrebooted = []
    softreboot_errors = {}
    for result_msg, nodes in results.items():
        if result_msg == "OK":
            for node in nodes:
                remaining_nodes.remove(node)
                softrebooted.append(node.name)
            nodes_manager.change_nodes_bootup_status(
                nodes=nodes, booted=False, cause=reboot_cause, method="soft-reboot")
            nodes_manager.record_nodes_boot_start(nodes)
        else:
            for node in nodes:
                softreboot_errors[node.name] = result_msg.lower()
    wf.update_env(softrebooted=softrebooted, softreboot_errors=softreboot_errors)
    wf.next()


def wf_hard_reboot_nodes_poe(wf, requester, remaining_nodes, **env):
    if len(remaining_nodes) > 0:
        if requester is not None and requester.has_hook("client_hard_reboot"):
            hard_reboot_method_name = requester.get_hard_reboot_method_name()
            hard_reboot_steps = [wf_client_hard_reboot]
        else:
            hard_reboot_method_name = "PoE-reboot"
            # kev
            hard_reboot_steps = [wf_filter_poe_rebootable, wf_poe_reboot]
        wf.insert_steps(hard_reboot_steps)
        wf.update_env(hard_reboot_method_name=hard_reboot_method_name)
    else:
        wf.update_env(
            hardrebooted=[], hardreboot_errors={}, hard_reboot_method_name="none"
        )
    wf.next()

# kev
def wf_hard_reboot_nodes_wol(wf, requester, remaining_nodes, hardreboot_errors, nodes_manager, **env):
    if len(remaining_nodes) > 0:
        hard_reboot_method_name = "poe-reboot"
        hard_reboot_steps = [wf_wol_off, wf_wol_on]
        wf.insert_steps(hard_reboot_steps)
        wf.update_env(hard_reboot_method_name=hard_reboot_method_name)
    else:
        wf.update_env(
            hardrebooted=[], hardreboot_errors={}, hard_reboot_method_name="none"
        )
    wf.next()

def wf_wol_off(wf, requester, remaining_nodes, hardreboot_errors, db, nodes_manager, ev_loop, **env):
    already_off = []
    not_off = []
    off_macs = db.get_wol_off_macs()
    
    for node in remaining_nodes:
        if node.mac in off_macs:
            already_off.append(node)
        else:
            not_off.append(node)
    
    node_request(
        ev_loop,
        remaining_nodes,
        "SHUTDOWN %(mac)s --hard ",
        wf_wol_shutdown_callback,
        dict(wf=wf, remaining_nodes=remaining_nodes,db=db, hardreboot_errors=hardreboot_errors,
                nodes_manager=nodes_manager, ev_loop=ev_loop),
                
    )

def wf_wol_shutdown_callback(results, wf, remaining_nodes, db, hardreboot_errors, nodes_manager, ev_loop):
    
    in_hardreboot_errors = {}
    powered_off=[]
    for result_msg, nodes in results.items():
        if result_msg == "OK":
            for node in nodes:
                db.record_wol_status(node.mac, False, "reboot")
                powered_off.append(node)
            nodes_manager.change_nodes_bootup_status(
                nodes=remaining_nodes, booted=False,
                cause="reboot", method="WoL hard-reboot")
        else:
            for node in nodes:
                in_hardreboot_errors[node.name] = result_msg.lower()

    hardreboot_errors.update(**in_hardreboot_errors)
    wf.update_env(powered_off=remaining_nodes)
    timeout_at = time() + WOL_REBOOT_DELAY
    
    ev_loop.plan_event(ts=timeout_at, callback=wf.next)

def wol_boot(powered_off, db):
    for node in powered_off:
        wol = Waker(get_walt_subnet())
        wol.makeMagicPacket(node.mac)
        wol.sendPacket(wol.packet, node.ip)
        db.record_wol_status(node.mac, True, "reboot")

def wf_wol_on(wf, requester, powered_off, db, hardreboot_errors, nodes_manager, **env):
    wol_boot(powered_off, db)
    env["ev_loop"].plan_event(ts=time()+WOL_REBOOT_DELAY, 
                callback=wol_boot, powered_off=powered_off, db=db)

    nodes_manager.record_nodes_boot_start(powered_off) # now powered on
    for n in powered_off:
        if n.name in hardreboot_errors:
            hardreboot_errors[n.name] += ", trying boot through wake-on-lan, check again in a few seconds"
    wf.update_env(
        hardrebooted=[n.name for n in powered_off],
        hardreboot_errors=hardreboot_errors,
    )
    wf.next()


def wf_client_hard_reboot(wf, requester, remaining_nodes, nodes_manager, reboot_cause,
                          hard_reboot_method_name, **env):
    mac_to_name = {node.mac: node.name for node in remaining_nodes}
    mac_to_node = {node.mac: node for node in remaining_nodes}
    node_macs = tuple(mac_to_name.keys())
    mac_hardrebooted, mac_hardreboot_errors = requester.hard_reboot_nodes(node_macs)
    hardrebooted = [mac_to_node[mac] for mac in mac_hardrebooted]
    if len(hardrebooted) > 0:
        nodes_manager.change_nodes_bootup_status(
            nodes=hardrebooted, booted=False,
            cause=reboot_cause, method=hard_reboot_method_name)
        nodes_manager.record_nodes_boot_start(hardrebooted)
    wf.update_env(
        hardrebooted=[mac_to_name[mac] for mac in mac_hardrebooted],
        hardreboot_errors={
            mac_to_name[mac]: error for mac, error in mac_hardreboot_errors.items()
        },
    )
    wf.next()


def wf_filter_poe_rebootable(wf, nodes_manager, remaining_nodes, **env):
    hardreboot_errors = {}
    connectivity = nodes_manager.devices.get_multiple_connectivity_info(
            tuple(node.mac for node in remaining_nodes))
    # kev
    poe_rebootable_nodes = []
    for node in remaining_nodes.copy():
        sw_info, sw_port = connectivity.get(node.mac, (None, None))
        if sw_info is not None and sw_port is not None:
            if sw_info.conf.get("poe.reboots", False) is True:
                poe_rebootable_nodes.append(node)
                pass  # ok, allowed
            else:
                hardreboot_errors[node.name] = "forbidden on switch"
        else:
            hardreboot_errors[node.name] = "unknown LLDP network position"
    wf.update_env(hardreboot_errors=hardreboot_errors, poe_rebootable_nodes=poe_rebootable_nodes)
    wf.next()


def wf_poe_reboot(
    wf, db, blocking, poe_rebootable_nodes, hardreboot_errors, **env
):
    if len(poe_rebootable_nodes) == 0:
        # nothing to do here
        wf.update_env(hardrebooted=[])
        wf.next()
        return
    not_already_off, already_off = [], []
    off_macs = db.get_poe_off_macs()
    for node in poe_rebootable_nodes:
        if node.mac in off_macs:
            already_off.append(node)
        else:
            not_already_off.append(node)
    wf.update_env(
        not_already_off=not_already_off, already_off=already_off, powered_off=[]
    )
    if len(not_already_off) > 0:
        wf.insert_steps(
            [
                wf_poe_poweroff,
                wf_poe_after_poweroff,
                wf_poe_poweron,
                wf_poe_after_poweron,
            ]
        )
    else:
        wf.insert_steps([wf_poe_poweron, wf_poe_after_poweron])
    wf.next()


def wf_poe_poweroff(wf, ev_loop, blocking, not_already_off, hardreboot_errors,
                    nodes_manager, reboot_cause, **env):
    blocking.nodes_set_poe(wf.next, not_already_off, False, "hard-reboot")
    nodes_manager.change_nodes_bootup_status(
        nodes=not_already_off, booted=False,
        cause=reboot_cause, method="PoE hard-reboot")


def wf_poe_after_poweroff(wf, poweroff_result, ev_loop, hardreboot_errors, **env):
    powered_off, in_hardreboot_errors = poweroff_result
    hardreboot_errors.update(**in_hardreboot_errors)
    wf.update_env(powered_off=powered_off)
    timeout_at = time() + POE_REBOOT_DELAY
    ev_loop.plan_event(ts=timeout_at, callback=wf.next)


def wf_poe_poweron(
    wf, ev_loop, blocking, already_off, powered_off, hardreboot_errors, **env
):
    all_off = already_off + powered_off
    if len(all_off) > 0:
        blocking.nodes_set_poe(wf.next, all_off, True)
    else:
        wf.update_env(poweron_result=([], {}))
        wf.next()


def wf_poe_after_poweron(wf, poweron_result, hardreboot_errors, nodes_manager, **env):
    powered_on, in_hardreboot_errors = poweron_result
    nodes_manager.record_nodes_boot_start(powered_on)
    hardreboot_errors.update(**in_hardreboot_errors)
    remaining_nodes = env["remaining_nodes"]
    for n in powered_on:
        remaining_nodes.remove(n)
    wf.update_env(hardrebooted=[n.name for n in powered_on], remaining_nodes=remaining_nodes)
    wf.next()


def wf_reply_requester(
    wf,
    requester,
    nodes_manager,
    task_callback,
    hard_only,
    vmrebooted,
    softrebooted,
    hardrebooted,
    softreboot_errors,
    hardreboot_errors,
    hard_reboot_method_name,
    **env
):
    rebooted = tuple(vmrebooted) + tuple(softrebooted) + tuple(hardrebooted)
    if len(rebooted) > 0:
        logline = format_sentence_about_nodes("%s: rebooted OK.", rebooted)
        if requester is None:
            nodes_manager.logs.platform_log("nodes", logline)
        else:
            requester.stdout.write(f"{logline}\n")
    if len(hardreboot_errors) == 0:
        # hard reboot is the last step, and it was applied to all nodes still not
        # rebooted at this time => having no hard reboot error means we could
        # eventually reboot all requested nodes.
        # in this case we can be brief and not detail how each node was rebooted.
        task_callback("OK")
    else:
        # not all went well
        per_errors = defaultdict(list)
        for node_name in hardreboot_errors:
            errors = (hardreboot_errors[node_name],)
            if node_name in softreboot_errors:  # if soft reboot was tried too
                errors += (softreboot_errors[node_name],)
            per_errors[errors].append(node_name)
        for errors, node_names in per_errors.items():
            if len(errors) == 1:  # no soft reboot error, just a poe reboot error
                hard_error = errors[0]
                explain = "failed %s (%s)" % (hard_reboot_method_name, hard_error)
            else:
                hard_error, soft_error = errors
                explain = "failed soft-reboot (%s) and %s (%s)" % (
                    soft_error,
                    hard_reboot_method_name,
                    hard_error,
                )
            logline = format_sentence_about_nodes("%s: " + explain, node_names)
            if requester is None:
                nodes_manager.logs.platform_log("nodes", logline, error=True)
            else:
                requester.stderr.write(f"{logline}\n")
        # unblock client
        task_callback("FAILED")
    wf.next()
