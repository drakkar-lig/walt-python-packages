import pickle
import re
from time import time

from walt.common.tools import get_mac_address
from walt.server import const
from walt.server.processes.db.postgres import PostgresDB
from walt.server.tools import get_server_ip

EV_AUTO_COMMIT = 0
EV_AUTO_COMMIT_PERIOD = 2
LOGS_AGGREGATION_THRESHOLD_SECS = 0.002


class ServerDB(PostgresDB):
    def __init__(self):
        # parent constructor
        PostgresDB.__init__(self)
        # timestamp for logs deframentation
        self.timestamp_last_logs = None

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
                    confirmed BOOLEAN);""")
        self.execute("""CREATE TABLE IF NOT EXISTS images (
                    fullname TEXT PRIMARY KEY);""")
        self.execute("""CREATE TABLE IF NOT EXISTS nodes (
                    mac TEXT REFERENCES devices(mac),
                    image TEXT REFERENCES images(fullname),
                    model TEXT,
                    booted BOOLEAN DEFAULT FALSE);""")
        self.execute("""CREATE TABLE IF NOT EXISTS switches (
                    mac TEXT REFERENCES devices(mac),
                    model TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS logstreams (
                    id SERIAL PRIMARY KEY,
                    issuer_mac TEXT REFERENCES devices(mac),
                    name TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS logs (
                    stream_id INTEGER REFERENCES logstreams(id),
                    timestamp TIMESTAMP,
                    line TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                    username TEXT,
                    timestamp TIMESTAMP,
                    name TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS poeoff (
                    mac TEXT REFERENCES devices(mac),
                    port INTEGER,
                    reason TEXT);""")
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
        self.execute("""CREATE INDEX IF NOT EXISTS logstreams_issuer_mac_name_idx
                         ON logstreams ( issuer_mac, name );""")
        self.execute("""CREATE INDEX IF NOT EXISTS devices_ip_idx
                         ON devices ( ip );""")
        self.execute("""CREATE INDEX IF NOT EXISTS checkpoints_username_idx
                         ON checkpoints ( username );""")
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

    def column_exists(self, table_name, column_name):
        col_info = self.select_unique(
            "information_schema.columns",
            table_schema="public",
            table_name=table_name,
            column_name=column_name,
        )
        return col_info is not None

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
        if self.timestamp_last_logs is not None:
            self.defragment_last_logs(self.timestamp_last_logs)
            self.timestamp_last_logs = None
        self.commit()

    def defragment_last_logs(self, timestamp_last_logs):
        self.execute(
            """
            WITH q1 AS (
                    SELECT l.*,
                      EXTRACT(EPOCH FROM(timestamp - (lag(timestamp, 1) OVER w))) > %s \
                        AS high_delay
                    FROM logs l, logstreams s
                    WHERE l.stream_id = s.id
                      AND s.mode = 'chunk'
                      AND timestamp >= %s
                    WINDOW w AS (PARTITION BY l.stream_id ORDER BY timestamp ASC)),
                 q2 AS (
                    SELECT *, (sum(coalesce(high_delay::int, 0)) OVER w) AS group_id
                    FROM q1
                    WINDOW w AS (PARTITION BY stream_id ORDER BY timestamp ASC))
            SELECT stream_id, min(timestamp) AS timestamp,
                   replace(string_agg(line, '+' ORDER BY timestamp), '''+b''', '') \
                     AS line
            INTO TEMPORARY TABLE aggregated_logs
            FROM q2
            GROUP BY stream_id, group_id;
        """,
            (LOGS_AGGREGATION_THRESHOLD_SECS, timestamp_last_logs),
        )
        self.execute(
            """
            DELETE FROM logs l
            WHERE l.timestamp >= %s
              AND l.stream_id IN (
                SELECT id FROM logstreams WHERE mode = 'chunk'
            );
        """,
            (timestamp_last_logs,),
        )
        self.execute("""
            INSERT INTO logs
            SELECT * FROM aggregated_logs;
        """)
        self.execute("""
            DROP TABLE aggregated_logs;
        """)

    def create_server_logs_cursor(self, **kwargs):
        sql, args = self.format_logs_query("l.*", ordering="l.timestamp", **kwargs)
        return self.create_server_cursor(sql, args)

    def get_logstream_ids(self, issuers):
        if issuers is None:
            return self.select_no_fetch("logstreams")
        else:
            issuer_names = """('%s')""" % "','".join(issuers)
            sql = """   SELECT s.*
                        FROM logstreams s, devices d
                        WHERE s.issuer_mac = d.mac
                          AND d.name IN %s;""" % issuer_names
            return self.execute(sql)

    def count_logs(
        self, history, streams=None, issuers=None, stream_mode=None, **kwargs
    ):
        unpickled_history = (pickle.loads(e) if e else None for e in history)
        # filter relevant streams
        stream_ids = []
        if streams:
            streams_re = re.compile(streams)
        for row in self.get_logstream_ids(issuers):
            if streams:
                matches = streams_re.findall(row.name)
                if len(matches) == 0:
                    continue  # discard this one
            if stream_mode:
                if row.mode != stream_mode:
                    continue  # discard this one
            stream_ids.append(str(row.id))
        if len(stream_ids) == 0:
            return 0  # no streams => no logs
        # note: we can release the constraint on issuers and stream mode
        # since we restrict to relevant logstreams
        # (cf. stream_ids variable we just computed)
        sql, args = self.format_logs_query(
            "count(*)",
            history=unpickled_history,
            stream_ids=stream_ids,
            issuers=None,
            stream_mode=None,
            **kwargs,
        )
        return self.execute(sql, args)[0][0]

    def format_logs_query(
        self,
        projections,
        ordering=None,
        issuers=None,
        history=(None, None),
        stream_ids=None,
        stream_mode=None,
        **kwargs,
    ):
        args = []
        constraints = ["s.issuer_mac = d.mac", "l.stream_id = s.id"]
        if stream_ids:
            stream_ids_sql = """(%s)""" % ",".join(
                str(stream_id) for stream_id in stream_ids
            )
            constraints.append("s.id IN %s" % stream_ids_sql)
        if stream_mode:
            constraints.append(f"s.mode = '{stream_mode}'")
        if issuers:
            issuer_names = """('%s')""" % "','".join(issuers)
            constraints.append("d.name IN %s" % issuer_names)
        start, end = history
        if start:
            constraints.append("l.timestamp > %s")
            args.append(start)
        if end:
            constraints.append("l.timestamp < %s")
            args.append(end)
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

    def forget_device(self, dev_name):
        self.execute(
            """
            DELETE FROM logs l USING devices d, logstreams s
                WHERE d.name = %s AND s.issuer_mac = d.mac AND l.stream_id = s.id;
            DELETE FROM logstreams s USING devices d
                WHERE d.name = %s AND s.issuer_mac = d.mac;
            DELETE FROM nodes n USING devices d WHERE d.name = %s AND d.mac = n.mac;
            DELETE FROM switches s USING devices d WHERE d.name = %s AND d.mac = s.mac;
            DELETE FROM topology t USING devices d WHERE d.name = %s AND d.mac = t.mac1;
            DELETE FROM topology t USING devices d WHERE d.name = %s AND d.mac = t.mac2;
            DELETE FROM poeoff po USING devices d WHERE d.name = %s AND d.mac = po.mac;
            DELETE FROM devices d WHERE d.name = %s;
        """,
            (dev_name,) * 8,
        )
        self.commit()

    def insert_multiple_logs(self, records):
        if len(records) > 0:
            record = records[0]
            if self.timestamp_last_logs is None:
                self.timestamp_last_logs = record["timestamp"]
            else:
                self.timestamp_last_logs = min(
                    self.timestamp_last_logs, record["timestamp"]
                )
        # due to buffering, we might still get stream_ids of a device
        # recently forgotten, which could lead to a foreign constraint violation
        # (stream_id no longer exists in the logstream table).
        # we just ignore those log records.
        cols, formats, values = self.get_insert_cols_and_values("logs", records)
        l_dot_cols = ",".join(("l." + col) for col in cols.split(","))
        sql = """INSERT INTO logs(%s)
                 SELECT %s
                 FROM (
                    VALUES %s
                 ) l (%s), logstreams s
                 WHERE l.stream_id = s.id""" % (
            cols,
            l_dot_cols,
            formats,
            cols,
        )
        self.c.execute(sql + ";", values)
        # print(f'Inserted {self.c.rowcount} log records')

    def get_user_images(self, username):
        sql = f"""  SELECT i.fullname, count(n.mac)>0 as in_use
                    FROM images i
                    LEFT JOIN nodes n ON i.fullname = n.image
                    WHERE fullname like '{username}/%'
                    GROUP BY i.fullname;"""
        return self.execute(sql)

    def record_poe_port_status(self, sw_mac, sw_port, poe_status, reason=None):
        if poe_status is True:  # poe on
            self.execute(
                """DELETE FROM poeoff
                                   WHERE mac = %s
                                     AND port = %s;""",
                (sw_mac, sw_port),
            )
        else:  # poe off
            assert reason is not None
            self.execute(
                """INSERT INTO poeoff
                            VALUES (%s, %s, %s);""",
                (sw_mac, sw_port, reason),
            )
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
