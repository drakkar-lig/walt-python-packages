import numpy as np
import time, re
from pathlib import Path

from walt.server.processes.main.network.service import ServiceRestarter
from walt.server.processes.main.network.service import async_systemd_service_restart_cmd
from walt.server.tools import get_dns_servers, get_server_ip, get_walt_subnet, ip

NAMED_STATE_DIR = Path("/var/lib/walt/services/named")
NAMED_CONF = NAMED_STATE_DIR / "named.conf"
NAMED_WALT_FWD_ZONE = "walt.forward.zone"
NAMED_WALT_REV_ZONE_PATTERN = "walt.%(rev_zone_name)s.reverse.zone"
NAMED_PID_FILE = "/run/walt/named/named.pid"

def dump_warning(comment_char='#'):
    return """
#
# DO NOT EDIT THIS FILE
#
# It is automatically generated by the walt system
# and updated when needed.
#
""".replace('#', comment_char)

CONF_PATTERN = dump_warning() + """

options {
    directory "%(named_state_dir)s";
    pid-file "%(named_pid_file)s";
    listen-on { %(walt_server_ip)s; };
    listen-on-v6 { none; };
    forwarders {
        %(dns_forwarders)s;
    };
};

# avoid failure trying to read /etc/bind/rndc.key
controls {};
# don't return IPv6 addresses to walt nodes
server ::/0 { bogus yes; };

zone "walt" IN {
    type master;
    file "%(named_walt_fwd_zone)s";
    allow-update { none; };
};

%(rev_zones)s

include "/etc/bind/named.conf.default-zones";
"""

# if we have more than a /24, we will get several
# reverse zones

REV_ZONE_DECL_PATTERN = """
zone "%(rev_zone_name)s" IN {
    type master;
    file "%(rev_zone_file)s";
    allow-update { none; };
};
"""

WALT_FWD_ZONE_PATTERN = dump_warning(";") + """
;
; BIND data file for walt zone
;
$TTL    604800
@   IN  SOA server.walt. root.server.walt. (
         %(serial)s     ; Serial
             604800     ; Refresh
              86400     ; Retry
            2419200     ; Expire
             604800 )   ; Negative Cache TTL
;
@                            IN NS    server.walt.
walt-server                  IN CNAME server

"""

WALT_REV_ZONE_PATTERN = dump_warning(";") + """
;
; BIND data file for walt %(rev_zone_name)s reverse zone
;
$TTL    604800
@   IN  SOA server.walt. root.server.walt. (
         %(serial)s     ; Serial
             604800     ; Refresh
              86400     ; Retry
            2419200     ; Expire
             604800 )   ; Negative Cache TTL
;
@   IN NS  server.walt.

"""


def serial_removed(zone_content):
    return re.sub(r'^.*Serial$', '', zone_content, flags=re.MULTILINE)


def identity(x):
    return x


def possibly_update_file(file_path, new_content, diff_preprocessing = identity):
    old_content = ""
    if file_path.exists():
        old_content = file_path.read_text()
    if diff_preprocessing(new_content) != diff_preprocessing(old_content):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(new_content)
        return True  # yes, updated
    return False


def np_column_to_file_content(col):
    return "".join(np.char.add(col.astype(str), "\n"))


def update_named_conf(dns_info):
    changed = False
    serial = str(int(time.time()))
    fwd_zone_content = WALT_FWD_ZONE_PATTERN % dict(
            serial = serial
    )
    fwd_zone_content += np_column_to_file_content(dns_info.fwd_zone_entry)
    fwd_zone_file = NAMED_STATE_DIR / NAMED_WALT_FWD_ZONE
    changed |= possibly_update_file(fwd_zone_file, fwd_zone_content,
                   diff_preprocessing=serial_removed)
    rev_zone_files = set()
    rev_zone_decls = []
    for rev_zone_name in np.unique(dns_info.rev_zone_name):
        rev_zone_file = NAMED_STATE_DIR / (
                NAMED_WALT_REV_ZONE_PATTERN % dict(
                    rev_zone_name = rev_zone_name
                )
        )
        rev_zone_files.add(rev_zone_file)
        rev_zone_decl = REV_ZONE_DECL_PATTERN % dict(
                rev_zone_name = rev_zone_name,
                rev_zone_file = rev_zone_file
        )
        rev_zone_decls.append(rev_zone_decl)
        rev_zone_content = WALT_REV_ZONE_PATTERN % dict(
                serial = serial,
                rev_zone_name = rev_zone_name
        )
        zone_dns_info = dns_info[dns_info.rev_zone_name == rev_zone_name]
        rev_zone_content += np_column_to_file_content(zone_dns_info.rev_zone_entry)
        changed |= possibly_update_file(rev_zone_file, rev_zone_content,
                   diff_preprocessing=serial_removed)
    # remove obsolete zone files
    prev_rev_zone_files = set(NAMED_STATE_DIR.glob('walt.*.reverse.zone'))
    for rev_zone_file in (prev_rev_zone_files - rev_zone_files):
        rev_zone_file.unlink()
        changed = True
    dns_forwarders = map(str, get_dns_servers())
    conf = CONF_PATTERN % dict(
            named_state_dir = NAMED_STATE_DIR,
            named_pid_file = NAMED_PID_FILE,
            walt_server_ip = get_server_ip(),
            dns_forwarders = '; '.join(dns_forwarders),
            named_walt_fwd_zone = NAMED_STATE_DIR / NAMED_WALT_FWD_ZONE,
            rev_zones = "\n".join(rev_zone_decls)
    )
    changed |= possibly_update_file(NAMED_CONF, conf)
    return changed


WALT_SUBNET = str(get_walt_subnet())
QUERY_DNS_INFO = f"""
WITH q1 as (
    SELECT
        ip,
        CASE WHEN type = 'server' THEN 'server'
             ELSE name
        END as name,
        string_to_array(ip, '.') as arr_ip
    FROM devices
    WHERE ip IS NOT NULL
      AND ip::inet << '{WALT_SUBNET}'::cidr
    ORDER BY ip::inet
)
SELECT
    arr_ip[3] || '.' || arr_ip[2] || '.' || arr_ip[1] || '.in-addr.arpa'
        as rev_zone_name,
    RPAD(arr_ip[4], 3, ' ') || ' IN PTR ' || name || '.walt.'
        as rev_zone_entry,
    RPAD(name, 28, ' ') || ' IN A     ' || ip
        as fwd_zone_entry
FROM q1;
"""


class DNSServer:
    def __init__(self, db, ev_loop):
        self.db = db
        restart_cmd = async_systemd_service_restart_cmd(
                "walt-server-named.service", allow_reload=True)
        self.restarter = ServiceRestarter(ev_loop, "named", restart_cmd)

    def update(self, force=False, cb=None):
        dns_info = self.db.execute(QUERY_DNS_INFO)
        changed = update_named_conf(dns_info)
        if changed:
            self.restarter.inc_config_version()
        if (not self.restarter.uptodate()) or force:
            self.restarter.restart(cb=cb)
        else:
            if cb is not None:
                cb()

    def wf_update(self, wf, force=False, **env):
        self.update(force=force, cb=wf.next)
