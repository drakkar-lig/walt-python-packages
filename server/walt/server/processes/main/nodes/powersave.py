from collections import defaultdict
from heapq import heappush, heappop
from time import time

from walt.common.formatting import format_sentence_about_nodes
from walt.server.workflow import Workflow

NODE_DEFAULT_POWERSAVE_TIMEOUT = 5 * 60  # 5 minutes
SQL_GET_POWERSAVE_TIMEOUT = f"""\
NULLIF(COALESCE(d.conf->'powersave.timeout',
                '{NODE_DEFAULT_POWERSAVE_TIMEOUT}'::jsonb),
       'null'::jsonb)::int AS timeout"""


class PowersaveManager:
    def __init__(self, server):
        self.server = server
        # Indicate at which time we should poweroff a node
        self._poweroff_ts_per_mac = {}
        # Indicate the set of free nodes
        self._mac_of_free_nodes = set()
        # Indicate if there is already a periodic check procedure running
        self._check_in_progress = False
        # Heap queue indicating time and mac of next poweroffs,
        # as tuples (ts, mac).
        # Some of the entries may be obsolete and will be ignored when
        # reading this queue.
        # There are two cases marking an entry obsolete:
        # - the mac is not longer a key of self._poweroff_ts_per_mac
        # - self._poweroff_ts_per_mac[mac] != ts
        self._pending_poweroffs = []
        # Timestamps of the self._check() calls already registered on
        # the event loop
        self._planned_checks = set()
        # Some nodes may be in continuous use so powersave is disabled
        # until this continuous use ends (e.g., `walt node shell`).
        # This dictionary indicates the number of continuous uses
        # per mac. If this number would be 0, then there is no entry
        # for this mac.
        self._continuous_uses_per_mac = {}
        # Indicate the configured delay after which the node should
        # be powered off if still free and idle.
        self._powersave_timeout_per_mac = {}
        # note: for the list of devices powered off at a given time
        # we rather rely on the database.

    def record_start_use(self, node_mac):
        """Record start of a countinuous use of this node (e.g. shell)"""
        self._poweroff_ts_per_mac.pop(node_mac, None)
        self._continuous_uses_per_mac[node_mac] = (
            self._continuous_uses_per_mac.get(node_mac, 0) +1
        )

    def record_end_use(self, node_mac):
        """Record end of a countinuous use of this node (e.g. shell)"""
        self._continuous_uses_per_mac[node_mac] -= 1
        if self._continuous_uses_per_mac[node_mac] == 0:
            del self._continuous_uses_per_mac[node_mac]
            if node_mac in self._mac_of_free_nodes:
                self._reset_node_mac_poweroff_timeout(node_mac)
                self._plan_check()

    def _get_powersave_timeout(self, node_mac):
        if node_mac in self._powersave_timeout_per_mac:
            return self._powersave_timeout_per_mac[node_mac]
        powersave_timeout = self.db.execute(f"""
            SELECT {SQL_GET_POWERSAVE_TIMEOUT}
            FROM devices d
            WHERE d.mac = %s""", (node_mac,))
        self._powersave_timeout_per_mac[node_mac] = (
                powersave_timeout
        )
        return powersave_timeout

    def _reset_node_mac_poweroff_timeout(self, node_mac):
        if node_mac in self._continuous_uses_per_mac:
            return
        powersave_timeout = self._get_powersave_timeout(node_mac)
        if powersave_timeout is None:
            # someone disabled powersave on this node
            # (walt node config <node> powersave.timeout=none)
            self._poweroff_ts_per_mac.pop(node_mac, None)
            return
        # plan powering off this node
        ts = time() + powersave_timeout
        self._poweroff_ts_per_mac[node_mac] = ts
        heappush(self._pending_poweroffs, (ts, node_mac))

    def check_usable(self, requester, nodes):
        off_macs = self.server.db.get_poe_off_macs(reason="powersave")
        unusable_node_names = []
        for node in nodes:
            if node.mac in off_macs:
                powersave_timeout = self._get_powersave_timeout(node.mac)
                if powersave_timeout == 0:
                    unusable_node_names.append(node.name)
        if len(unusable_node_names) > 0:
            sentence = ("%s: currently in permanent powersave mode, "
                        "and therefore unusable(unusables).\n"
                        "See 'walt help show powersave'.\n")
            msg = format_sentence_about_nodes(sentence, unusable_node_names)
            requester.stderr.write(msg)
            return False
        return True

    def _record_node_use(self, node_mac):
        # if a free node is in use,
        # reset the timeout for 2 more hours before powersave
        if node_mac in self._mac_of_free_nodes:
            self._reset_node_mac_poweroff_timeout(node_mac)

    def _peak_next_check(self):
        while len(self._pending_poweroffs) > 0:
            ts, mac = self._pending_poweroffs[0]
            if self._poweroff_ts_per_mac.get(mac) != ts:
                # obsolete check
                heappop(self._pending_poweroffs)
                continue
            return ts, mac
        return None, None

    def _plan_check(self):
        if self._check_in_progress is True:
            return
        ts, mac = self._peak_next_check()
        if ts is None:
            return
        if ts not in self._planned_checks:
            self._planned_checks.add(ts)
            self.server.ev_loop.plan_event(
                   ts=ts, callback=self._check, check_ts=ts)

    def _check(self, check_ts):
        self._check_in_progress = True
        self._planned_checks.discard(check_ts)
        off_macs = self.server.db.get_poe_off_macs()
        now = time()
        macs_to_be_turned_off = []
        while True:
            ts, mac = self._peak_next_check()
            if ts is None:
                break
            if mac in off_macs:
                # we managed to turn the port off at previous step,
                # so we no longer need this timeout entry
                self._poweroff_ts_per_mac.pop(mac, None)
                continue
            if ts <= now:
                # remove this item from the priority queue
                heappop(self._pending_poweroffs)
                # we will process this mac below
                macs_to_be_turned_off.append(mac)
            else:
                break  # this element and next ones are in the future
        if len(macs_to_be_turned_off) == 0:
            # notify concurrent code this check is done, plan next one
            self._check_in_progress = False
            self._plan_check()
        else:
            to_be_turned_off = (
                    self.server.devices.get_multiple_device_info_for_macs(
                        macs_to_be_turned_off, include_connectivity=True)
            )
            wf = Workflow(
                [
                    self._wf_toggle_power_on_nodes,
                    self._wf_after_toggle_power_on_nodes,
                    self._wf_end_check,
                ],
                requester=None,
                poe_toggle_nodes=to_be_turned_off,
                poe_toggle_value=False,
            )
            wf.run()

    def _wf_end_check(self, wf, **env):
        # notify concurrent code this check is done, plan next one
        self._check_in_progress = False
        self._plan_check()
        wf.next()

    def _wf_plan_check(self, wf, **env):
        self._plan_check()
        wf.next()

    def _wf_toggle_power_on_nodes(
        self, wf, requester, poe_toggle_nodes, poe_toggle_value, **env
    ):
        nodes_ok, nodes_ko, _ = self.server.poe.filter_poe_rebootable(poe_toggle_nodes)
        if len(nodes_ko) > 0:
            for node in nodes_ko:
                # retry after a new powersave timeout delay
                self._reset_node_mac_poweroff_timeout(node.mac)
        wf.update_env(poe_toggle_nodes=nodes_ok)
        if len(nodes_ok) > 0:
            wf.insert_steps([self.server.poe.wf_nodes_set_poe])
            wf.update_env(nodes=nodes_ok,
                          poe_status=poe_toggle_value,
                          reason="powersave")
            wf.next()
        else:
            wf.update_env(nodes_ok=poe_toggle_nodes[:0],  # none
                          poe_errors={})
            wf.next()

    def _wf_after_toggle_power_on_nodes(self, wf, nodes_ok, poe_errors,
                                        poe_toggle_nodes, poe_toggle_value,
                                        requester, **env):
        if len(poe_errors) > 0:
            verb = "reactivate" if poe_toggle_value is True else "turn off"
            node_per_name = {n.name: n for n in poe_toggle_nodes}
            per_error = defaultdict(list)
            for node_name, error in poe_errors.items():
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
                    self.server.logs.platform_log(
                            "powersave.error", line=sentence, error=True)
        if len(nodes_ok) > 0:
            if poe_toggle_value is True:
                self.server.nodes.record_nodes_boot_start(nodes_ok)
            else:
                self.server.nodes.change_nodes_bootup_status(
                    nodes=nodes_ok, booted=False,
                    cause="powersave", method="PoE")
        wf.next()

    def _wf_forget_obsolete_topology_entry(self, wf, obsolete_mac_in_topology, **env):
        self.server.db.forget_topology_entry_for_mac(obsolete_mac_in_topology)
        wf.next()

    def restore(self):
        # detect free nodes by the fact they boot their '*-free' image
        for row in self.server.db.execute(f"""
                SELECT d.mac, {SQL_GET_POWERSAVE_TIMEOUT}
                FROM devices d, nodes n
                WHERE d.mac = n.mac
                  AND n.image = 'waltplatform/' || n.model || '-free:latest';
                """):
            self._mac_of_free_nodes.add(row.mac)
            self._powersave_timeout_per_mac[row.mac] = row.timeout
            self._reset_node_mac_poweroff_timeout(row.mac)
        self._plan_check()

    def update_node_timeout(self, node_mac, timeout):
        self._powersave_timeout_per_mac[node_mac] = timeout
        self._reset_node_mac_poweroff_timeout(node_mac)
        self._plan_check()

    def handle_event(self, ev_name, *args, **kwargs):
        ev_cb = getattr(self, f"{ev_name}_event")
        return ev_cb(*args, **kwargs)

    def set_image_event(self, node_mac, is_free_image):
        if is_free_image:
            # new free node
            self._mac_of_free_nodes.add(node_mac)
            self._reset_node_mac_poweroff_timeout(node_mac)
            self._plan_check()
        else:
            # no longer a free node
            self._mac_of_free_nodes.discard(node_mac)
            self._poweroff_ts_per_mac.pop(node_mac, None)
            # the node may currently be in powersave mode, but we do not
            # power it back yet, this will be done later by the reboot_nodes()
            # procedure.

    def reboot_event(self, nodes):
        for node in nodes:
            self._record_node_use(node.mac)
        self._plan_check()

    def rescan_restore_poe_event(self):
        off_macs = self.server.db.get_poe_off_macs()
        for mac in self._mac_of_free_nodes:
            if mac not in off_macs and mac not in self._poweroff_ts_per_mac:
                # PoE was temporarily restored for the node having this mac,
                # so restart the corresponding poweroff timeout.
                self._reset_node_mac_poweroff_timeout(mac)
        self._plan_check()

    def node_bootup_event(self, node):
        # if the node is free, restart its powersave timeout
        self._record_node_use(node.mac)
        off_macs = self.server.db.get_poe_off_macs()
        if node.mac in off_macs:
            # bootup event for a node supposedly powered off!
            # this means it was moved somewhere else.
            # we must:
            # 1. re-enable PoE on the switch port
            # 2. forget the previous position in network topology table
            wf = Workflow(
                [
                    self._wf_toggle_power_on_nodes,
                    self._wf_after_toggle_power_on_nodes,
                    self._wf_forget_obsolete_topology_entry,
                    self._wf_plan_check,
                ],
                requester=None,
                poe_toggle_nodes=[node],
                poe_toggle_value=True,
                obsolete_mac_in_topology=node.mac,
            )
            wf.run()
        else:
            self._plan_check()

    def _wf_forget_node_mac(self, wf, obsolete_node_mac, **env):
        self._poweroff_ts_per_mac.pop(obsolete_node_mac, None)
        self._continuous_uses_per_mac.pop(obsolete_node_mac, None)
        self._mac_of_free_nodes.discard(obsolete_node_mac)
        self._powersave_timeout_per_mac.pop(obsolete_node_mac, None)
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
            self._record_node_use(node.mac)
        if len(off_nodes) == 0:
            self._plan_check()
        else:
            requester.stdout.write(
                "Reactivating related switch port(s) in powersave mode.\n"
            )
            wf.update_env(poe_toggle_nodes=off_nodes, poe_toggle_value=True)
            wf.insert_steps(
                [self._wf_toggle_power_on_nodes,
                 self._wf_after_toggle_power_on_nodes,
                 self._wf_plan_check]
            )
        wf.next()
