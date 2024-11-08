import functools
import numpy as np
import sys

from walt.server.processes.main.workflow import Workflow

WARNING_DEVICE_RESCAN_POE_OFF = """\
NOTE: WALT previously turned off PoE on some switch ports for automatic powersaving.
NOTE: This command will re-enable PoE on these ports.
NOTE: However, devices connected there may not be re-detected before a little time.
NOTE: Re-running a scan in 10 minutes may give better results.
"""


class PoEManager:
    def __init__(self, server):
        self.server = server

    def _build_dict_errors(self, node_names, poe_errors):
        arr = np.empty((2, len(node_names)), object)
        arr[0], arr[1] = node_names, poe_errors
        return dict(arr.T)

    def filter_poe_rebootable(self, nodes):
        nodes = self.server.devices.ensure_connectivity_info(nodes)
        mask_poe_error = nodes.poe_error != None
        if mask_poe_error.any():
            nodes_ok = nodes[~mask_poe_error]
            nodes_ko = nodes[mask_poe_error]
            errors = self._build_dict_errors(nodes_ko.name, nodes_ko.poe_error)
            return nodes_ok, nodes_ko, errors
        else:
            return nodes, nodes[:0], {}

    def restore_poe_on_all_ports(self):
        sw_ports_info = self._get_poe_switch_ports_off()
        if len(sw_ports_info) > 0:
            wf = Workflow([self._wf_multiple_sw_ports_set_poe,
                           self._wf_end_of_restore_poe],
                          sw_ports_info=sw_ports_info,
                          poe_status=True)
            wf.run()

    def wf_rescan_restore_poe_on_switch_ports(self, wf, requester, devices, **env):
        sw_ports_info = self._get_poe_switch_ports_off(devices)
        if len(sw_ports_info) > 0:
            self._print_req_stderr(requester, WARNING_DEVICE_RESCAN_POE_OFF)
            wf.insert_steps([self._wf_multiple_sw_ports_set_poe,
                             self._wf_end_of_restore_poe,
                             self._wf_after_rescan_restore_poe])
            wf.update_env(sw_ports_info=sw_ports_info,
                          poe_status=True)
        wf.next()

    def wf_nodes_set_poe(self, wf, nodes, poe_status, reason=None, **env):
        # turning off a PoE port without giving a reason is not allowed
        assert not (poe_status is False and reason is None)
        assert len(nodes) > 0
        # we should have connectivity info ready, and all nodes
        # should be poe-rebootable
        assert isinstance(nodes, np.recarray)
        assert "poe_error" in nodes.dtype.names
        assert (nodes.poe_error == None).all()
        wf.update_env(sw_ports_info=nodes)
        wf.insert_steps([self._wf_multiple_sw_ports_set_poe,
                         self._wf_end_of_nodes_set_poe])
        wf.next()

    def _wf_end_of_nodes_set_poe(self, wf, nodes, poe_results, **env):
        mask_succeeded = poe_results.retcode == 0
        nodes_ok = nodes[mask_succeeded]
        nodes_ko = nodes[~mask_succeeded]
        poe_errors = poe_results[~mask_succeeded]
        errors = self._build_dict_errors(nodes_ko.name,
                                         poe_results[~mask_succeeded].error)
        wf.update_env(nodes_ok=nodes_ok,
                      poe_errors=errors)
        wf.next()

    def _wf_multiple_sw_ports_set_poe(self, wf, sw_ports_info, **env):
        poe_results = np.empty(sw_ports_info.size,
                        dtype=[("retcode", int), ("error", object)]).view(np.recarray)
        wf.update_env(poe_results=poe_results)
        wf.insert_steps([self._wf_after_multiple_sw_ports_set_poe])
        wf.map_as_parallel_steps(self._wf_sw_port_set_poe, sw_ports_info, poe_results)
        wf.next()

    def _wf_sw_port_set_poe(self, wf, sw_port_info, poe_result, poe_status, **env):
        cb = functools.partial(self._wf_save_poe_result, wf, sw_port_info,
                               poe_result, **env)
        status_arg = "on" if poe_status is True else "off"
        self.server.ev_loop.do(
                f"walt-set-poe {sw_port_info.sw_ip} {sw_port_info.sw_port} "
                f"{status_arg} "
                f"{sw_port_info.sw_snmp_version} {sw_port_info.sw_snmp_community}",
                cb, silent=False, catch_stderr=True)

    def _wf_save_poe_result(self, wf, sw_port_info, poe_result, retcode, stderr_msg,
                            **env):
        poe_result.retcode = retcode
        if retcode != 0:
            poe_result.error = stderr_msg.strip().decode("ascii")
        wf.next()

    def _wf_after_multiple_sw_ports_set_poe(self, wf, sw_ports_info, poe_status,
                                            poe_results, reason=None, **env):
        # record the changes in database where the operation succeeded
        mask_succeeded = poe_results.retcode == 0
        sw_ports_ok = sw_ports_info[mask_succeeded]
        self.server.db.record_poe_ports_status(sw_ports_ok, poe_status, reason)
        # let next wf step handle errors
        wf.next()

    def _get_poe_switch_ports_off(self, devices=None):
        sql = """SELECT sw_d.mac as sw_mac,
                        po.port as sw_port,
                        sw_d.ip as sw_ip,
                        sw_d.name as sw_name,
                        sw_d.conf->'snmp.version' as sw_snmp_version,
                        sw_d.conf->'snmp.community' as sw_snmp_community,
                        NULL as poe_error
                 FROM devices sw_d, poeoff po
                 WHERE sw_d.mac = po.mac"""
        if devices is None:
            # all switches
            sw_ports_info = self.server.db.execute(sql)
        else:
            # selected switches
            device_macs = tuple(devices.mac)
            sw_ports_info = self.server.db.execute(
                sql + """ AND sw_d.mac IN %s""",
                (device_macs,)
            )
        return sw_ports_info

    def _format_poe_error_messages(self, sw_ports_info, poe_results):
        messages = []
        mask_failed = poe_results.retcode != 0
        # print one message per distinct error string and switch name
        if mask_failed.any():
            ports_ko = sw_ports_info[mask_failed]
            poe_errors = poe_results[mask_failed]
            while len(ports_ko) > 0:
                error = poe_errors[0].error
                err_mask = poe_errors.error == error
                err_ports = ports_ko[err_mask]
                while len(err_ports) > 0:
                    sw_name = err_ports[0].sw_name
                    sw_mask = err_ports.sw_name == sw_name
                    sw_ports = err_ports[sw_mask].sw_port
                    if len(sw_ports) == 1:
                        sw_ports_desc = f"{sw_name} port {sw_ports[0]}"
                    else:
                        sw_ports_list = ", ".join(str(p) for p in sorted(sw_ports))
                        sw_ports_desc = f"{sw_name} ports {sw_ports_list}"
                    messages.append(
                        "WARNING: Failed to restore PoE on switch "
                        + f"{sw_ports_desc} -- {error}!"
                    )
                    err_ports = err_ports[~sw_mask]
                ports_ko = ports_ko[~err_mask]
                poe_errors = poe_errors[~err_mask]
        return messages

    def _print_req_stderr(self, requester, msg):
        if requester is None:
            print(msg, file=sys.stderr)
        else:
            requester.stderr.write(f"{msg}\n")
            requester.stderr.flush()

    def _wf_end_of_restore_poe(self, wf, sw_ports_info, poe_results,
                               requester=None, **env):
        messages = self._format_poe_error_messages(sw_ports_info, poe_results)
        if len(messages) > 0:
            self._print_req_stderr(requester, "\n".join(messages))
        wf.next()

    def _wf_after_rescan_restore_poe(self, wf, **env):
        self.server.nodes.powersave.handle_event("rescan_restore_poe")
        wf.next()
