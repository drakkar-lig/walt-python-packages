import numpy as np
import psycopg2.extras
import re
from datetime import datetime, timedelta
from psycopg2.extensions import register_adapter, AsIs
from time import time

from walt.common.tcp import MyPickle as pickle
from walt.common.tools import get_mac_address
from walt.server import const
from walt.server.processes.db.postgres import PostgresDB
from walt.server.tools import get_server_ip

# allow psycopg2 to interpret numpy types properly
register_adapter(np.int32, AsIs)
register_adapter(np.float64, AsIs)

EV_AUTO_COMMIT = 0
EV_AUTO_COMMIT_PERIOD = 2
LOGS_AGGREGATION_THRESHOLD_SECS = 0.002


class ServerDB(PostgresDB):
    def __init__(self):
        # parent constructor
        PostgresDB.__init__(self)

    def prepare(self):
        PostgresDB.prepare(self)  # parent method
        # create the db schema
        # tables
        self.execute("""CREATE TABLE IF NOT EXISTS devices (
                    mac TEXT PRIMARY KEY,
                    ip TEXT,
                    name TEXT,
                    type TEXT,
                    virtual BOOLEAN DEFAULT FALSE,
                    conf JSONB DEFAULT '{}');""")
        self.execute("""CREATE TABLE IF NOT EXISTS topology (
                    mac1 TEXT REFERENCES devices(mac),
                    port1 INTEGER,
                    mac2 TEXT REFERENCES devices(mac),
                    port2 INTEGER,
                    confirmed BOOLEAN,
                    last_seen TIMESTAMP WITH TIME ZONE);""")
        self.execute("""CREATE TABLE IF NOT EXISTS images (
                    fullname TEXT PRIMARY KEY);""")
        self.execute("""CREATE TABLE IF NOT EXISTS nodes (
                    mac TEXT REFERENCES devices(mac),
                    image TEXT REFERENCES images(fullname),
                    model TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS switches (
                    mac TEXT REFERENCES devices(mac),
                    model TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS switchports (
                    mac TEXT REFERENCES devices(mac),
                    port INTEGER,
                    name TEXT,
                    PRIMARY KEY (mac, port));""")
        self.execute("""CREATE TABLE IF NOT EXISTS logstreams (
                    id SERIAL PRIMARY KEY,
                    issuer_mac TEXT REFERENCES devices(mac),
                    name TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS logs (
                    stream_id INTEGER REFERENCES logstreams(id),
                    timestamp TIMESTAMP WITH TIME ZONE,
                    line TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                    username TEXT,
                    timestamp TIMESTAMP,
                    name TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS poeoff (
                    mac TEXT REFERENCES devices(mac),
                    port INTEGER,
                    reason TEXT);""")
        # We have two different tables "vpnnodes" and "vpnauth"
        # because in the case of "walt device forget" we may want
        # to forget a vpn node, but still keep track of the auth data
        # in case we want to revoke it in the future.
        # The device is identified by either a corresponding entry in
        # table vpnnodes or a non-NULL device_label value,
        # depending on whether the device was forgotten or not.
        self.execute("""CREATE TABLE IF NOT EXISTS vpnauth (
                    vpnmac TEXT PRIMARY KEY,
                    pubkeycert TEXT,
                    certid TEXT,
                    device_label TEXT,
                    revoked BOOLEAN DEFAULT FALSE);""")
        self.execute("""CREATE TABLE IF NOT EXISTS vpnnodes (
                    mac TEXT REFERENCES devices(mac),
                    vpnmac TEXT REFERENCES vpnauth(vpnmac));""")
        # migration v4 -> v5
        if not self.column_exists("devices", "conf"):
            self.execute("""ALTER TABLE devices
                            ADD COLUMN conf JSONB DEFAULT '{}';""")
            self.execute("""UPDATE devices d
                            SET conf = conf || (
                                    '{"lldp.explore":' || s.lldp_explore || ',' ||
                                    ' "poe.reboots":' || s.poe_reboot_nodes || '}'
                                )::jsonb
                            FROM switches s
                            WHERE s.mac = d.mac;""")
            self.execute("""UPDATE devices d
                            SET conf = conf || (
                                    '{"snmp.version": ' ||
                                        (s.snmp_conf::jsonb->'version')::text || ',' ||
                                    ' "snmp.community": ' ||
                                        (s.snmp_conf::jsonb->'community')::text || '}'
                                )::jsonb
                            FROM switches s
                            WHERE s.mac = d.mac AND s.snmp_conf IS NOT NULL;""")
            self.execute("""ALTER TABLE switches
                            DROP COLUMN snmp_conf,
                            DROP COLUMN lldp_explore,
                            DROP COLUMN poe_reboot_nodes;""")
            self.execute("""UPDATE devices d
                            SET conf = conf || \
                                    ('{"netsetup":' || n.netsetup || '}')::jsonb
                            FROM nodes n
                            WHERE n.mac = d.mac;""")
            self.execute("""ALTER TABLE nodes
                            DROP COLUMN netsetup;""")
            # When migrating to v5, walt image storage management moves from
            # docker to podman.
            # In order to avoid duplicating many old and unused images to podman
            # storage, we remove the reference of unused images from database.
            self.execute("""DELETE FROM images
                            WHERE fullname NOT IN (
                                SELECT DISTINCT image FROM nodes
                            );""")
        # migration v7 -> v8
        if not self.column_exists("logstreams", "mode"):
            self.execute("""CREATE TYPE logmode AS ENUM ('line', 'chunk');""")
            self.execute("""ALTER TABLE logstreams
                            ADD COLUMN mode logmode DEFAULT 'line';""")
        if self.column_exists("images", "ready"):
            self.execute("""DELETE FROM images WHERE ready = false;""")
            self.execute("""ALTER TABLE images DROP COLUMN ready;""")
        # logstreams.sender_mac renamed to logstreams.issuer_mac
        if self.column_exists("logstreams", "sender_mac"):
            self.execute(
                """ALTER TABLE logstreams RENAME COLUMN sender_mac TO issuer_mac;"""
            )
            # the following dropped index will be re-created below
            self.execute("""DROP INDEX IF EXISTS logstreams_sender_mac_name_idx;""")
        # indexes
        self.execute("""CREATE INDEX IF NOT EXISTS logs_timestamp_idx
                         ON logs ( timestamp );""")
        self.execute("""CREATE INDEX IF NOT EXISTS logs_stream_id_idx
                         ON logs ( stream_id );""")
        self.execute("""CREATE INDEX IF NOT EXISTS logstreams_issuer_mac_name_idx
                         ON logstreams ( issuer_mac, name );""")
        self.execute("""CREATE INDEX IF NOT EXISTS devices_ip_idx
                         ON devices ( ip );""")
        self.execute("""CREATE INDEX IF NOT EXISTS checkpoints_username_idx
                         ON checkpoints ( username );""")
        # migration v8.2 -> v8.3
        if self.column_exists("nodes", "booted"):
            self.execute("""ALTER TABLE nodes DROP COLUMN booted;""")
        # migration v9.0 -> v10.0
        if self.column_type("logs", "timestamp") == "timestamp without time zone":
            print("Updating logs database for new version... (this can take time)")
            self.execute("""ALTER TABLE logs
                            ALTER COLUMN timestamp TYPE timestamp with time zone;""")
            print("Updating logs database for new version: done")
        if not self.column_exists("topology", "last_seen"):
            self.execute("""ALTER TABLE topology
                            ADD COLUMN last_seen TIMESTAMP WITH TIME ZONE;""")
            self.execute("""UPDATE topology SET last_seen = now();""")
        # fix server entry
        self.fix_server_device_entry()
        # commit
        self.commit()

    def fix_server_device_entry(self):
        server_ip = get_server_ip()
        server_mac = get_mac_address(const.WALT_INTF)
        server_entry = self.select_unique("devices", mac=server_mac)
        if server_entry is None:
            self.insert(
                "devices",
                mac=server_mac,
                ip=server_ip,
                name="walt-server",
                type="server",
            )
        else:
            self.update(
                "devices",
                "mac",
                mac=server_mac,
                ip=server_ip,
                name="walt-server",
                type="server",
            )
        # ensure wrong entries were not left out by previous versions
        # of walt server code
        wrong_entries = self.execute(
            """SELECT mac FROM devices
                   WHERE mac != %s
                     AND (  ip = %s OR
                            type = 'server' OR
                            name = 'walt-server' );
                """,
            (server_mac, server_ip),
        )
        for entry in wrong_entries:
            self.execute(
                """
                DELETE FROM logs l USING logstreams s
                    WHERE s.issuer_mac = %s AND l.stream_id = s.id;
                DELETE FROM logstreams s WHERE s.issuer_mac = %s;
                DELETE FROM topology t WHERE t.mac1 = %s;
                DELETE FROM topology t WHERE t.mac2 = %s;
                DELETE FROM poeoff po WHERE po.mac = %s;
                DELETE FROM devices d WHERE d.mac = %s;
            """,
                (entry.mac,) * 6,
            )
            self.commit()

    def _column_info(self, table_name, column_name):
        return self.select_unique(
            "information_schema.columns",
            table_schema="public",
            table_name=table_name,
            column_name=column_name,
        )

    def column_exists(self, table_name, column_name):
        return self._column_info(table_name, column_name) is not None

    def column_type(self, table_name, column_name):
        return self._column_info(table_name, column_name).data_type

    # Some types of events are numerous and commiting the
    # database each time would be costly.
    # That's why we auto-commit every few seconds.
    def plan_auto_commit(self, ev_loop):
        ev_loop.plan_event(
            ts=time(),
            target=self,
            repeat_delay=EV_AUTO_COMMIT_PERIOD,
            ev_type=EV_AUTO_COMMIT,
        )

    def handle_planned_event(self, ev_type):
        assert ev_type == EV_AUTO_COMMIT
        self.commit()

    LOGS_SQL_PROJ = (
            "EXTRACT(EPOCH FROM l.timestamp)::float8 as timestamp, " +
            "l.line, " +
            "d.name as issuer, " +
            "s.name as stream")

    def create_server_logs_cursor(self, **kwargs):
        self.commit()
        sql, args = self.format_logs_query(
                ServerDB.LOGS_SQL_PROJ, ordering="l.timestamp", **kwargs)
        return self.create_server_cursor(sql, args)

    def get_multiple_connectivity_info(self, device_macs):
        row_values_placeholder = ",".join(["(%s)"] * len(device_macs))
        return self.execute(f"""
            with cte0 as (
                select * from (values {row_values_placeholder}) as t(device_mac)),
            cte1 as (
                select device_mac, mac2 as mac, port2 as port, confirmed, last_seen
                from topology, cte0
                where mac1 = device_mac
                union
                select device_mac, mac1 as mac, port1 as port, confirmed, last_seen
                from topology, cte0
                where mac2 = device_mac),
            cte2 as (
                select *,
                    ROW_NUMBER() OVER(
                        PARTITION BY device_mac
                        ORDER BY confirmed DESC, last_seen DESC, device_mac)
                    AS rownum from cte1)
            select dev_d.mac as dev_mac, dev_d.name as dev_name,
                   sw_d.mac as sw_mac, t.port as sw_port,
                   sw_d.ip as sw_ip,
                   sw_d.conf->'snmp.version' as sw_snmp_version,
                   sw_d.conf->'snmp.community' as sw_snmp_community,
                   CASE WHEN sw_d.ip is NULL OR t.port is NULL
                          THEN 'unknown LLDP network position'
                        WHEN not COALESCE((sw_d.conf->'poe.reboots')::bool, false)
                          THEN 'forbidden on switch'
                   END as poe_error
            from cte2 t
            left join switches s on s.mac = t.mac
            left join devices sw_d on sw_d.mac = s.mac
            left join devices dev_d on dev_d.mac = t.device_mac
            where rownum = 1""", device_macs)

    def count_logs(self, **kwargs):
        sql, args = self.format_logs_query("count(*)", **kwargs)
        return self.execute(sql, args)[0][0]

    def format_logs_query(
        self,
        projections,
        ordering=None,
        issuers=None,
        history=(None, None),
        stream_mode=None,
        streams_regexp=None,
        logline_regexp=None,
        exclude_consoles=False
    ):
        args = []
        constraints = ["s.issuer_mac = d.mac", "l.stream_id = s.id"]
        if stream_mode:
            constraints.append(f"s.mode = '{stream_mode}'")
        if issuers is not None:
            issuer_names = """('%s')""" % "','".join(issuers)
            constraints.append("d.name IN %s" % issuer_names)
        # note: prefix "(?e)" allows to restrict the regular expression syntax
        # of postgresql to the "ERE" (Extended Posix Regex)
        if streams_regexp is not None:
            constraints.append(f"s.name ~ %s")
            args.append("(?e)" + streams_regexp)
        if exclude_consoles:
            constraints.append("s.name ~ '$(?<!console)'")
        if logline_regexp is not None:
            constraints.append(f"l.line ~ %s")
            args.append("(?e)" + logline_regexp)
        start, end = history
        if start:
            constraints.append("l.timestamp > %s")
            args.append(datetime.fromtimestamp(start))
        if end:
            constraints.append("l.timestamp < %s")
            args.append(datetime.fromtimestamp(end))
        where_clause = self.get_where_clause_from_constraints(constraints)
        if ordering:
            ordering = "order by " + ordering
        else:
            ordering = ""
        return (
            "SELECT %s FROM devices d, logstreams s, logs l %s %s;"
            % (projections, where_clause, ordering),
            args,
        )

    def forget_device(self, mac):
        # note: We deliberately never remove the entries of
        # table vpnauth, in order to be able to revoke any key
        # in the future. But we update the device_label column.
        self.execute(
            """
            UPDATE vpnauth va
            SET device_label = (
                SELECT 'forgotten device "' ||
                    d.name || '" mac=' || d.mac
                FROM devices d
                WHERE d.mac = %s
            )
            FROM vpnnodes vn
            WHERE va.vpnmac = vn.vpnmac
              AND vn.mac = %s
            """, (mac, mac)
        )

        self.execute(
            """
            DELETE FROM logs l USING logstreams s
                WHERE s.issuer_mac = %s AND l.stream_id = s.id;
            DELETE FROM logstreams s WHERE s.issuer_mac = %s;
            DELETE FROM nodes n WHERE n.mac = %s;
            DELETE FROM switchports sp WHERE sp.mac = %s;
            DELETE FROM switches s WHERE s.mac = %s;
            DELETE FROM topology t WHERE t.mac1 = %s OR t.mac2 = %s;
            DELETE FROM poeoff po WHERE po.mac = %s;
            DELETE FROM vpnnodes vn WHERE vn.mac = %s;
            DELETE FROM devices d WHERE d.mac = %s;
        """,
            (mac,) * 10,
        )
        self.commit()

    def get_vpn_auth_keys(self):
        return self.execute("""
            SELECT va.certid, va.revoked,
                   (va.device_label is not NULL) as forgotten_device,
                   COALESCE(va.device_label,
                    'node "' || d.name || '" mac=' || d.mac) as device_label
            FROM vpnauth va
            LEFT JOIN vpnnodes vn
              ON vn.vpnmac = va.vpnmac
            LEFT JOIN devices d
              ON d.mac = vn.mac
        """)

    def revoke_vpn_auth_key(self, vpnmac):
        return self.execute("""
                UPDATE vpnauth
                SET revoked = true
                WHERE vpnmac = %s""",
                (vpnmac,))

    def insert_multiple_logs(self, records):
        # due to buffering, we might still get stream_ids of a device
        # recently forgotten, which could lead to a foreign constraint violation
        # (stream_id no longer exists in the logstream table).
        # the following query just ignores those log records.
        psycopg2.extras.execute_values(self.c, """
                INSERT INTO logs(timestamp,line,stream_id)
                SELECT TO_TIMESTAMP(l.timestamp),l.line,l.stream_id
                FROM (
                    VALUES %s
                ) l (timestamp,line,stream_id), logstreams s
                WHERE l.stream_id = s.id""",
                records)

    def get_user_images(self, username):
        sql = f"""  SELECT i.fullname, count(n.mac)>0 as in_use
                    FROM images i
                    LEFT JOIN nodes n ON i.fullname = n.image
                    WHERE fullname like '{username}/%'
                    GROUP BY i.fullname;"""
        return self.execute(sql)

    def get_all_images(self):
        sql = f"""  SELECT i.fullname, count(n.mac)>0 as in_use
                    FROM images i
                    LEFT JOIN nodes n ON i.fullname = n.image
                    GROUP BY i.fullname;"""
        return self.execute(sql)

    def record_poe_ports_status(self, sw_ports_info, poe_status, reason=None):
        if poe_status is True:  # poe on
            self.c.executemany(
                """DELETE FROM poeoff
                                   WHERE mac = %s
                                     AND port = %s;""",
                sw_ports_info[["sw_mac", "sw_port"]],
            )
        else:  # poe off
            assert reason is not None
            arr = np.empty(sw_ports_info.size,
                           dtype=[("sw_mac", object),
                                  ("sw_port", object),
                                  ("reason", object)]).view(np.recarray)
            arr[["sw_mac", "sw_port"]] = sw_ports_info[["sw_mac", "sw_port"]]
            arr["reason"] = reason
            psycopg2.extras.execute_values(self.c,
                    """INSERT INTO poeoff VALUES %s;""", arr)
        self.commit()

    def get_poe_off_macs(self, reason=None):
        """List mac addresses of devices connected on a switch port with PoE off."""
        if reason is None:
            # if reason is unspecified, match any reason
            sql_optional_condition = ""
            sql_values = ()
        else:
            sql_optional_condition = "AND po.reason = %s"
            sql_values = (reason, reason)
        return tuple(
            row.mac
            for row in self.execute(
                f"""
                 SELECT t.mac2 as mac
                 FROM topology t, poeoff po
                 WHERE po.mac = t.mac1
                   AND po.port = t.port1
                   {sql_optional_condition}
               UNION
                 SELECT t.mac1 as mac
                 FROM topology t, poeoff po
                 WHERE po.mac = t.mac2
                   AND po.port = t.port2
                   {sql_optional_condition};""",
                sql_values,
            )
        )

    def forget_topology_entry_for_mac(self, mac):
        self.execute(
            """DELETE FROM topology WHERE mac1 = %s OR mac2 = %s;""", (mac, mac)
        )
        self.commit()

    def update_node_location(self, node_mac, sw_mac, sw_port):
        # check if location of mac already existed in db
        db_locs = self.execute(
        """ SELECT mac2 as sw_mac, port2 as sw_port, confirmed
            FROM topology
            WHERE mac1 = %s
        UNION
            SELECT mac1 as sw_mac, port1 as sw_port, confirmed
            FROM topology
            WHERE mac2 = %s """, (node_mac, node_mac))
        if len(db_locs) == 1:
            db_loc = db_locs[0]
            if (db_loc.sw_mac, db_loc.sw_port) == (sw_mac, sw_port):
                # already known in db
                if not db_loc.confirmed:
                    # just have to set confirmed=True
                    macs = tuple(sorted((node_mac, sw_mac)))
                    self.execute(
                        """ UPDATE topology
                            SET confirmed = true
                            WHERE mac1 = %s
                              AND mac2 = %s """, macs)
                    self.commit()
                # nothing more to do
                return False  # location did not change
            else:
                # remove existing db entry for node_mac
                db_macs = tuple(sorted((node_mac, db_loc.sw_mac)))
                self.execute(
                        """ DELETE FROM topology
                            WHERE mac1 = %s
                              AND mac2 = %s """, db_macs)
                # continue below
        # remove any existing db entry at (sw_mac, sw_port)
        self.execute("""DELETE FROM topology
                        WHERE mac1 = %s
                        AND port1 = %s """, (sw_mac, sw_port))
        self.execute("""DELETE FROM topology
                        WHERE mac2 = %s
                        AND port2 = %s """, (sw_mac, sw_port))
        # insert the new entry
        if node_mac < sw_mac:
            args = (node_mac, sw_mac, None, sw_port)
        else:
            args = (sw_mac, node_mac, sw_port, None)
        self.execute("""INSERT INTO topology(mac1, mac2,
                             port1, port2, confirmed)
                        VALUES (%s, %s, %s, %s, true); """, args)
        self.commit()
        return True
