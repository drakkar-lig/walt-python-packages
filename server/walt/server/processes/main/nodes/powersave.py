from collections import defaultdict
from time import time

from walt.common.formatting import format_sentence_about_nodes
from walt.server.processes.main.workflow import Workflow

POWERSAVE_TIMEOUT = 2 * 60 * 60  # 2 hours


class PowersaveManager:
    def __init__(self, server):
        self.server = server
        self._poweroff_timeouts_per_mac = {}
        self._mac_of_free_nodes = set()
        self._next_check = None
        # note: for the list of devices powered off at a given time
        # we rather rely on the database.

    def _reset_node_mac_poweroff_timeout(self, node_mac):
        # we take care preserving the order of dictionary entries,
        # the first one having the earliest timeout, etc.
        # so here we cannot just update the entry, we remove it
        # and reinsert it so that it becomes the last entry.
        self._poweroff_timeouts_per_mac.pop(node_mac, None)
        self._poweroff_timeouts_per_mac[node_mac] = time() + POWERSAVE_TIMEOUT

    def _record_node_usage(self, node_mac):
        # if a free node is in use,
        # reset the timeout for 2 more hours before powersave
        if node_mac in self._mac_of_free_nodes:
            self._reset_node_mac_poweroff_timeout(node_mac)

    def _plan_check(self):
        if self._next_check is None and len(self._poweroff_timeouts_per_mac) > 0:
            self._next_check = next(iter(self._poweroff_timeouts_per_mac.values()))
            self.server.ev_loop.plan_event(ts=self._next_check, callback=self._check)

    def _check(self):
        off_macs = self.server.db.get_poe_off_macs()
        now = time()
        it = self._poweroff_timeouts_per_mac.copy().items()
        # print(
        #     f"_check off_macs={off_macs}",
        #     f"poweroff_timeouts={self._poweroff_timeouts_per_mac}",
        # )
        self._poweroff_timeouts_per_mac = {}
        macs_to_be_turned_off = []
        for mac, ts in it:
            if ts <= now:
                if mac not in off_macs:
                    macs_to_be_turned_off.append(mac)
            else:
                self._poweroff_timeouts_per_mac[mac] = ts
        if len(macs_to_be_turned_off) == 0:
            self._next_check = None  # notify concurrent code that this check is done
            self._plan_check()  # plan next one
        else:
            nodes_to_be_turned_off = [
                self.server.db.select_unique("devices", mac=mac)
                for mac in macs_to_be_turned_off
            ]
            wf = Workflow(
                [
                    self._wf_toggle_power_on_nodes,
                    self._wf_after_toggle_power_on_nodes,
                    self._wf_recurse_check,
                ],
                requester=None,
                poe_toggle_nodes=nodes_to_be_turned_off,
                poe_toggle_value=False,
            )
            wf.run()

    def _wf_recurse_check(self, wf, **env):
        # resurse in case things would have changed during the SNMP communication delay
        self._check()

    def _wf_toggle_power_on_nodes(
        self, wf, requester, poe_toggle_nodes, poe_toggle_value, **env
    ):
        for node in poe_toggle_nodes.copy():
            sw_info, sw_port = self.server.devices.get_connectivity_info(node.mac)
            if sw_info and sw_info.conf.get("poe.reboots", False) is True:
                pass  # ok, allowed
            else:  # unknown network position or forbidden on switch
                poe_toggle_nodes.remove(node)
                # retry after a new powersave timeout delay
                self._reset_node_mac_poweroff_timeout(node.mac)
        if len(poe_toggle_nodes) > 0:
            self.server.blocking.nodes_set_poe(
                wf.next, poe_toggle_nodes, poe_toggle_value, "powersave"
            )
        else:
            wf.update_env(poe_toggle_result=([], {}))
            wf.next()

    def _wf_after_toggle_power_on_nodes(
        self,
        wf,
        poe_toggle_result,
        poe_toggle_nodes,
        poe_toggle_value,
        requester,
        **env,
    ):
        toggled, error_per_name = poe_toggle_result
        if len(error_per_name) > 0:
            verb = "reactivate" if poe_toggle_value is True else "turn off"
            node_per_name = {n.name: n for n in poe_toggle_nodes}
            per_error = defaultdict(list)
            for node_name, error in error_per_name.items():
                per_error[error].append(node_name)
                # retry after a new powersave timeout delay
                node_mac = node_per_name[node_name].mac
                self._reset_node_mac_poweroff_timeout(node_mac)
            for error, node_names in per_error.items():
                sentence = format_sentence_about_nodes(
                    f"%s: warning, failed to {verb} PoE ({error})", node_names
                )
                if requester is not None:
                    requester.stderr.write(f"{sentence}\n")
                else:
                    self.server.logs.platform_log("powersave.error", sentence)
        self._plan_check()
        wf.next()

    def _wf_forget_obsolete_topology_entry(self, wf, obsolete_mac_in_topology, **env):
        self.server.db.forget_topology_entry_for_mac(obsolete_mac_in_topology)

    def restore(self):
        # init attributes considering nodes having their default image
        for row in self.server.db.execute("""
                SELECT mac
                FROM nodes
                WHERE image = 'waltplatform/' || model || '-default:latest';
                """):
            self._mac_of_free_nodes.add(row.mac)
            self._reset_node_mac_poweroff_timeout(row.mac)
        self._plan_check()

    def handle_event(self, ev_name, *args, **kwargs):
        ev_cb = getattr(self, f"{ev_name}_event")
        return ev_cb(*args, **kwargs)

    def set_image_event(self, node_mac, is_default_image):
        if is_default_image:
            # new free node
            self._mac_of_free_nodes.add(node_mac)
            self._reset_node_mac_poweroff_timeout(node_mac)
            self._plan_check()
        else:
            # no longer a free node
            self._mac_of_free_nodes.discard(node_mac)
            self._poweroff_timeouts_per_mac.pop(node_mac, None)
            # the node may currently be in powersave mode, but we do not
            # power it back yet, this will be done later by the reboot_nodes()
            # procedure.

    def reboot_event(self, nodes):
        for node in nodes:
            self._record_node_usage(node.mac)
        self._plan_check()

    def rescan_restore_poe_event(self):
        off_macs = self.server.db.get_poe_off_macs()
        for mac in self._mac_of_free_nodes:
            if mac not in off_macs and mac not in self._poweroff_timeouts_per_mac:
                # PoE was temporarily restored for the node having this mac,
                # so restart the corresponding poweroff timeout.
                self._reset_node_mac_poweroff_timeout(mac)
        self._plan_check()

    def node_bootup_event(self, node):
        off_macs = self.server.db.get_poe_off_macs()
        if node.mac in off_macs:
            # bootup event for a node supposedly powered off!
            # this means it was moved somewhere else.
            # we must:
            # 0. restart the powersave timeout
            # 1. re-enable PoE on the switch port
            # 2. forget the previous position in network topology table
            self._reset_node_mac_poweroff_timeout(node.mac)
            self._plan_check()
            wf = Workflow(
                [
                    self._wf_toggle_power_on_nodes,
                    self._wf_after_toggle_power_on_nodes,
                    self._wf_forget_obsolete_topology_entry,
                ],
                requester=None,
                poe_toggle_nodes=[node],
                poe_toggle_value=True,
                obsolete_mac_in_topology=node.mac,
            )
            wf.run()

    def _wf_forget_node_mac(self, wf, obsolete_node_mac, **env):
        self._poweroff_timeouts_per_mac.pop(obsolete_node_mac, None)
        wf.next()

    def wf_forget_device(self, wf, requester, device, **env):
        if device.type == "node":
            # the device is obsolete, but we should not let the PoE desactivated
            # on the related port if it is the case.
            wf.insert_steps([self.wf_wakeup_nodes, self._wf_forget_node_mac])
            wf.update_env(nodes=(device,), obsolete_node_mac=device.mac)
        wf.next()

    def wf_wakeup_nodes(self, wf, requester, nodes, **env):
        off_macs = self.server.db.get_poe_off_macs(reason="powersave")
        off_nodes = []
        for node in nodes:
            if node.mac in off_macs:
                off_nodes.append(node)
            # ensuring a node is woken up means we want to use it
            self._record_node_usage(node.mac)
        if len(off_nodes) == 0:
            self._plan_check()
        else:
            requester.stdout.write(
                "Reactivating related switch port(s) in powersave mode.\n"
            )
            wf.update_env(poe_toggle_nodes=off_nodes, poe_toggle_value=True)
            wf.insert_steps(
                [self._wf_toggle_power_on_nodes, self._wf_after_toggle_power_on_nodes]
            )
        wf.next()
