from pathlib import Path
from time import time
import pickle
import socket

from walt.common.netsetup import NetSetup
from walt.common.unix import bind_to_random_sockname
from walt.server.const import DHCPD_HEARTBEAT_PERIOD, DHCPD_DEVICES_FILE
from walt.server.const import DHCPD_CTRL_SOCK_PATH, DHCPD_VAR_LIB_PATH
from walt.server.tools import get_walt_subnet


QUERY_DEVICES_WITH_IP = f"""
    SELECT d.mac, ip, name, type,
        COALESCE((conf->'netsetup')::int, {NetSetup.LAN}) as netsetup,
        vn.vpnmac
    FROM devices d
    LEFT JOIN vpnnodes vn ON d.mac = vn.mac
    WHERE ip IS NOT NULL
      AND type != 'server'
      AND ip::inet << %s::cidr
"""


class DHCPServer(object):
    def __init__(self, db, ev_loop):
        self.db = db
        self.ev_loop = ev_loop
        self._remove_obsolete_conf()

    def _remove_obsolete_conf(self):
        """Remove obsolete conf from previous WALT versions."""
        for f in DHCPD_VAR_LIB_PATH.iterdir():
            if f.name.startswith("dhcpd."):
                f.unlink()

    def start_heartbeat(self):
        self.ev_loop.plan_event(
            ts=time(),
            target=self,
            repeat_delay=DHCPD_HEARTBEAT_PERIOD,
            ev_type="HEARTBEAT",
        )

    def handle_planned_event(self, ev_type):
        assert ev_type == "HEARTBEAT"
        if not self._send_command_to_dhcpd("HEARTBEAT")[0]:
            print("Warning: sending HEARTBEAT to walt-server-dhcpd failed.")

    def _send_command_to_dhcpd(self, cmd, *args, **kwargs):
        # DHCPD_CTL_SOCK should exist if walt-server-dhcpd is running
        if DHCPD_CTRL_SOCK_PATH.exists():
            dhcpd_ctl_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            bind_to_random_sockname(dhcpd_ctl_sock)
            try:
                dhcpd_ctl_sock.settimeout(1)  # safety net
                dhcpd_ctl_sock.connect(str(DHCPD_CTRL_SOCK_PATH))
                req = (cmd, args, kwargs)
                dhcpd_ctl_sock.send(pickle.dumps(req))
                resp = dhcpd_ctl_sock.recv(1024)
                if resp.startswith(b"OK"):
                    return True, resp[2:].decode().lstrip()
                if resp.startswith(b"FAILED"):
                    return False, resp[6:].decode().lstrip()
            except Exception:
                pass
            finally:
                dhcpd_ctl_sock.close()
        return False, "walt-server-dhcpd seems down"

    def update(self, cb=None):
        subnet = get_walt_subnet()
        devices = self.db.execute(QUERY_DEVICES_WITH_IP, (str(subnet),))
        devices_dump = pickle.dumps(devices)
        DHCPD_DEVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
        DHCPD_DEVICES_FILE.write_bytes(devices_dump)
        if not self._send_command_to_dhcpd("RELOAD_CONF")[0]:
            print("Warning: sending RELOAD_CONF to "
                  "walt-server-dhcpd failed.")
        if cb is not None:
            cb()
    def allocate_ip(self, mac):
        return self._send_command_to_dhcpd("ALLOCATE_IP", mac)
    def wf_update(self, wf, **env):
        self.update(cb=wf.next)
