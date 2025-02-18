#!/usr/bin/env python
import operator
import numpy as np
from time import time

from walt.common.tcp import Requests

NODE_DEFAULT_BOOT_RETRIES = 9
NODE_DEFAULT_BOOT_TIMEOUT = 180
NODE_MIN_BOOT_TIMEOUT = 60

np_extract_cause = np.vectorize(operator.methodcaller("get", "cause", None), otypes="O")


def np_apply_mapping(column, mapping):
    return np.vectorize(mapping.get, otypes="O")(column)


class NodeBootupStatusListener:
    REQ_ID = Requests.REQ_NOTIFY_BOOTUP_STATUS

    def __init__(self, manager, sock_file, sock_files_per_ip, **kwargs):
        self.manager = manager
        self.sock_file = sock_file
        self.sock_files_per_ip = sock_files_per_ip
        self.node_ip, _ = self.sock_file.getpeername()
        self.sock_files_per_ip[self.node_ip] = self.sock_file
        self.sock_file.write(b'OK\n')
        self.set_keepalive()
        self._confirmed = False

    def set_keepalive(self):
        self.sock_file.set_keepalive()

    # let the event loop know what we are reading on
    def fileno(self):
        if self.sock_file.closed:
            return None
        return self.sock_file.fileno()

    def _add_booted_evt(self, booted, **details):
        self.manager.add_booted_event(self.node_ip, booted, details)

    # handle_event() will be called when the event loop detects
    # something for us
    def handle_event(self, ts):
        try:
            if len(self.sock_file.read(1)) == 1:
                # all is fine
                if not self._confirmed:
                    self._confirmed = True
                    self._add_booted_evt(True)
                return True  # continue
            else:
                err = "empty read"
        except Exception as e:
            err = str(e)
        # If we are here, there was an Exception or an empty read, which means
        # the connection was lost.
        # however, detecting a lost connection might take time and actually
        # happen after the node has rebooted and established a new connection.
        # thus we verify that we are managing the latest connection of this node.
        if (
                self._confirmed and
                self.sock_files_per_ip.get(self.node_ip) is self.sock_file
           ):
            # note: self._add_booted_evt() will not print a message if the node
            # was already down (e.g., because it was explicitely rebooted, or
            # because the powersave module turned it off).
            self._add_booted_evt(False,
                                 cause="unknown",
                                 note="server-detected disconnection")
        return False  # we should be removed from the event loop

    def close(self):
        if self.sock_file:
            if self.sock_files_per_ip[self.node_ip] is self.sock_file:
                del self.sock_files_per_ip[self.node_ip]
            self.sock_file.close()
            self.sock_file = None


class NodeBootupStatusManager(object):
    def __init__(self, tcp_server, nodes_manager):
        self._sock_files_per_ip = {}
        self._booted_events = []
        self._nodes = nodes_manager
        self._ev_loop = nodes_manager.ev_loop
        self._db = nodes_manager.db
        self._logs = nodes_manager.logs
        self._devices = nodes_manager.devices
        self._booted_macs = set()
        self._boot_info = {}
        self._boot_info_table = None
        self._next_bg_process = None
        self._bg_processing = False
        self._cleaning_up = False
        for cls in [NodeBootupStatusListener]:
            tcp_server.register_listener_class(
                manager=self,
                req_id=cls.REQ_ID,
                cls=cls,
                sock_files_per_ip=self._sock_files_per_ip,
            )

    def cleanup(self):
        self._cleaning_up = True

    def get_booted_macs(self):
        return self._booted_macs.copy()

    def forget_device(self, mac):
        self._booted_macs.discard(mac)  # if ever it was inside
        if mac in self._boot_info:
            del self._boot_info[mac]
        mask = (self._boot_info_table.mac != mac)
        self._boot_info_table = self._boot_info_table[mask]
        # verify we just have a view of the original array
        assert self._boot_info_table.base is not None

    def _record_boot_info(self, boot_info):
        dt_names = list(boot_info.dtype.names[1:])  # 'mac' excluded
        self._boot_info_table = boot_info
        self._boot_info = dict(zip(boot_info["mac"], boot_info[dt_names]))
        self._plan_bg_process()

    def restore(self):
        # initialize _boot_info
        # note: 3 cases must be considered for conf->'boot.timeout':
        # * it may be an integer
        # * it may be missing, in which case a default value NODE_DEFAULT_BOOT_TIMEOUT
        #   is returned
        # * it may be disabled, in which case the value stored is 'null'::jsonb and
        #   the value to return is None.
        now = time()
        boot_info = self._db.execute(f"""
            SELECT
                mac,
                NULLIF(COALESCE(conf->'boot.timeout',
                                '{NODE_DEFAULT_BOOT_TIMEOUT}'::jsonb),
                       'null'::jsonb)::int
                    AS timeout,
                COALESCE((conf->'boot.retries')::int, {NODE_DEFAULT_BOOT_RETRIES})
                    AS retries,
                COALESCE((conf->'boot.retries')::int, {NODE_DEFAULT_BOOT_RETRIES})
                    AS remaining_retries,
                'startup' AS cause,
                EXTRACT(EPOCH FROM current_timestamp)::float8 AS boot_start_time
            FROM devices
            WHERE type = 'node';
        """)
        self._record_boot_info(boot_info)

    def add_booted_event(self, *evt):
        self._booted_events.append(evt)
        self._plan_bg_process()

    def update_node_boot_retries(self, node_mac, retries):
        old_retries = self._boot_info[node_mac]["retries"]
        old_remaining_retries = self._boot_info[node_mac]["remaining_retries"]
        remaining_retries = old_remaining_retries + retries - old_retries
        if remaining_retries < 0:
            remaining_retries = 0
        self._boot_info[node_mac].retries = retries
        self._boot_info[node_mac].remaining_retries = remaining_retries
        self._plan_bg_process()

    def update_node_boot_timeout(self, node_mac, timeout):
        self._boot_info[node_mac].timeout = timeout
        self._plan_bg_process()

    def record_nodes_boot_start(self, nodes):
        now = time()
        update_macs = set(node.mac for node in nodes) - self._booted_macs
        update_mask = np.isin(self._boot_info_table.mac, list(update_macs))
        self._boot_info_table.boot_start_time[update_mask] = now
        self._plan_bg_process()

    def register_node(self, mac):
        dt = self._boot_info_table.dtype
        values = (mac, NODE_DEFAULT_BOOT_TIMEOUT, NODE_DEFAULT_BOOT_RETRIES,
                  NODE_DEFAULT_BOOT_RETRIES, "startup", time())
        self._record_boot_info(np.append(
                self._boot_info_table,
                np.array([values], dtype=dt)).view(np.recarray))

    def reset_boot_retries(self, nodes):
        update_macs = set(node.mac for node in nodes)
        update_mask = np.isin(self._boot_info_table.mac, list(update_macs))
        retries = self._boot_info_table.retries[update_mask]
        self._boot_info_table.remaining_retries[update_mask] = retries

    def change_nodes_bootup_status(self, nodes, booted=True, **details):
        self._booted_events += [(node.ip, booted, details) for node in nodes]
        self._plan_bg_process()

    def _mask_valid_boot_timeout(self):
        # the node should not be booted yet
        mask = ~np.isin(self._boot_info_table.mac, list(self._booted_macs))
        # node's timeout should not have been set to none in config
        mask &= (self._boot_info_table.timeout != None)
        # node's remaining_retries should not be 0
        mask &= (self._boot_info_table.remaining_retries != 0)
        # node should not be in powersave mode
        mask &= (self._boot_info_table.cause != "powersave")
        return mask

    def _plan_bg_process(self):
        # if bg process is already running, just let it recall
        # _plan_bg_process() when it is done
        if self._bg_processing:
            return
        # otherwise, if some events are pending, call bg process immediately
        if len(self._booted_events) > 0:
            self._bg_process()
            return
        # otherwise, use the event loop to start bg process when the
        # next node should be booted
        next_boot_check = self._next_bg_process
        mask = self._mask_valid_boot_timeout()
        if mask.any():
            boot_info = self._boot_info_table[mask]
            min_boot_check = np.min(boot_info.boot_start_time + boot_info.timeout)
            if next_boot_check is None:
                next_boot_check = min_boot_check
            else:
                next_boot_check = min(min_boot_check, next_boot_check)
        if next_boot_check is None:
            return  # nothing to monitor
        if self._next_bg_process is None or self._next_bg_process > next_boot_check:
            self._next_bg_process = next_boot_check
            self._ev_loop.plan_event(ts=next_boot_check, callback=self._bg_process)

    def _bg_process(self):
        if self._cleaning_up:
            return
        if self._bg_processing:
            return
        self._bg_processing = True
        self._next_bg_process = None
        # process events
        self._bg_process_booted_events()
        # check boot timeouts
        failing_nodes = self._bg_boot_check()
        # reboot nodes if needed and then plan next bg process
        if len(failing_nodes) > 0:
            def cb(status):
                self._bg_processing = False
                self._plan_bg_process()
            self._nodes.reboot_nodes(None, cb, failing_nodes, True, "bootup timeout",
                              reset_boot_retries=False)
        else:
            self._bg_processing = False
            self._plan_bg_process()

    def _bg_process_booted_events(self):
        if len(self._booted_events) > 0:
            dt = [("ip", "O"), ("booted", "?"), ("details", "O")]
            booted_evts = np.array(self._booted_events, dtype=dt)
            self._booted_events = []    # reset
            # if we have several events for one ip, consider the last one only
            if booted_evts.size > 1:
                booted_evts = np.flip(booted_evts)
                _, uniq_idx = np.unique(booted_evts["ip"], return_index=True)
                booted_evts = booted_evts[uniq_idx]
            # analyse content of details
            dt = [("ip", "O"), ("booted", "?"), ("cause", "O"), ("ll_details", "O")]
            processed_evts = np.empty(booted_evts.size, dtype=dt)
            processed_evts[["ip", "booted"]] = booted_evts[["ip", "booted"]]
            # extract cause
            processed_evts["cause"] = np_extract_cause(booted_evts["details"])
            # compute logline details
            logline_details = np.vectorize(repr)(booted_evts["details"])
            logline_details = np.char.replace(logline_details, "'", '')
            processed_evts["ll_details"] = np.char.strip(logline_details, "{}")
            # note: if a virtual node was just removed or a node was forgotten,
            # ip is missing from db, and the event is just ignored.
            values_holder = ("%s," * processed_evts.size)[:-1]
            sql = f"""WITH events(ip, booted, cause, ll_details) AS (
                        VALUES {values_holder}
                    )
                    SELECT d.name, d.mac, e.booted, e.cause, e.ll_details,
                           NULL as old_booted, NULL as logline
                    FROM events e
                    LEFT JOIN devices d ON e.ip = d.ip
                    WHERE d.ip IS NOT NULL"""
            evts = self._db.execute(sql, processed_evts.tolist())
            evts.old_booted = np.isin(evts.mac, list(self._booted_macs))
            # ignore events not changing current status
            mask = np.bitwise_xor(evts.booted, evts.old_booted).astype(bool)
            if mask.any():
                evts = evts[mask]
                now = time()
                # prepare logline column
                evts.logline = "node " + evts.name
                if evts.booted.any():   # "booted" events
                    mask = evts.booted.astype(bool)
                    # update booted macs
                    self._booted_macs |= set(evts[mask].mac)
                    # update logline column
                    evts.logline[mask] += " is booted"
                    # unblock any related "walt node wait" command.
                    for node_info in evts[mask]:
                        self._nodes.wait_info.node_bootup_event(node_info)
                        self._nodes.powersave.node_bootup_event(node_info)
                if not evts.booted.all():  # "down" events
                    mask = ~(evts.booted.astype(bool))
                    macs = evts[mask].mac
                    # update booted macs
                    self._booted_macs -= set(macs)
                    # update logline column
                    evts.logline[mask] += " is down"
                    details_mask = mask & (evts.ll_details != "")
                    ll_details = " (" + evts.ll_details[details_mask] + ")"
                    evts.logline[details_mask] += ll_details
                    # note: if this node went down unexpectedly, we have no idea
                    # when it started to reboot, so set boot_start_time to now
                    # (i.e., the time when we detect it is down).
                    # if it was expected, then boot_start_time will be updated
                    # again shortly (e.g., in the case of a hard-reboot, when PoE
                    # is re-enabled).
                    update_mask = np.isin(self._boot_info_table.mac, macs)
                    self._boot_info_table.boot_start_time[update_mask] = now
                    retries = self._boot_info_table.retries[update_mask]
                    self._boot_info_table.remaining_retries[update_mask] = retries
                    if len(set(evts[mask].cause)) == 1:
                        # same cause for all events (likely), fast path
                        self._boot_info_table.cause[update_mask] = evts[mask].cause[0]
                    else:
                        # generic case
                        cause_per_mac = dict(evts[mask][["mac", "cause"]])
                        update_macs = self._boot_info_table.mac[update_mask]
                        update_causes = np_apply_mapping(update_macs, cause_per_mac)
                        self._boot_info_table.cause[update_mask] = update_causes
                # emit log lines
                self._logs.platform_log("nodes", lines=evts.logline)
        self._plan_bg_process()

    def _bg_boot_check(self):
        mask = self._mask_valid_boot_timeout()
        if mask.any():
            now = time()
            boot_info = self._boot_info_table[mask]
            submask = (now >= boot_info.boot_start_time + boot_info.timeout)
            if submask.any():
                indices = np.flatnonzero(mask)[submask]
                self._boot_info_table.remaining_retries[indices] -= 1
                # We will hard reboot this node below, but if hard-reboot fails,
                # boot start time will not be updated. So we artificially set it
                # now to force a delay of NODE_DEFAULT_BOOT_TIMEOUT before the next
                # hard-reboot try, in this failure case.
                self._boot_info_table.boot_start_time[indices] = now
                boot_info = self._boot_info_table[indices]
                where_sql = "d.mac = ANY(%s)"
                failing_nodes = self._devices.get_multiple_device_info(
                                    where_sql, (list(boot_info.mac),))
                name_per_mac = dict(failing_nodes[["mac", "name"]])
                names = np_apply_mapping(boot_info.mac, name_per_mac)
                loglines = names + ": boot timeout reached, trying hard-reboot "
                mask_more_tries = (boot_info.remaining_retries > 0)
                num_retries = boot_info.remaining_retries[mask_more_tries]
                num_retries = num_retries.astype(str).astype("O")
                loglines[mask_more_tries] += "(" + num_retries + " retries left)."
                loglines[~mask_more_tries] += "(last try)."
                self._logs.platform_log("nodes", lines=loglines)
                return failing_nodes
        return []   # no failing nodes
