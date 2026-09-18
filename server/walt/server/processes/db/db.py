import locale
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
EV_CLEANUP_DELETED = 1
# gradual removal of logs of deleted devices is performed in small
# bounded steps, so that the (single-threaded) db process keeps some
# time to handle other requests in between.
CLEANUP_DELETED_BATCH = 500      # max logs deleted per batch
CLEANUP_DELETED_BUDGET = 0.01    # max time spent per cleanup step
CLEANUP_DELETED_DELAY = 0.01     # delay before the next cleanup step
LOGS_AGGREGATION_THRESHOLD_SECS = 0.002


class ServerDB(PostgresDB):
    def __init__(self, ev_loop):
        # parent constructor
        PostgresDB.__init__(self)
        # the ev_loop of the server-db process, used to schedule
        # step-by-step cleanup operations without blocking it.
        self.ev_loop = ev_loop
        # even if we remove several devices in a short time,
        # only one progressive cleanup process is needed,
        # so let's track whether it is already running or not.
        self._cleaning_up_removed_devices = False

    def _create_views(self):
        self.execute("""CREATE VIEW devices AS
                        SELECT * FROM alldevices
                        WHERE type != 'deleted' """)
        self.execute("""CREATE VIEW deleted_macs AS
                        SELECT mac FROM alldevices
                        WHERE type = 'deleted'""")
        in_deleted_macs = "IN (SELECT * FROM deleted_macs)"
        self.execute(f"""CREATE VIEW logstreams AS
                        SELECT * FROM alllogstreams
                        WHERE issuer_mac NOT {in_deleted_macs}""")
        self.execute(f"""CREATE VIEW logs AS
                         SELECT * FROM alllogs
                         WHERE stream_id NOT IN (
                             SELECT id FROM alllogstreams
                             WHERE issuer_mac {in_deleted_macs}
                         )""")

    def _create_tables(self):
        self.execute("""CREATE TABLE alldevices (
            mac TEXT COLLATE "C" PRIMARY KEY,
            ip TEXT COLLATE "C",
            name TEXT COLLATE "C",
            type TEXT COLLATE "C",
            virtual BOOLEAN DEFAULT FALSE,
            conf JSONB DEFAULT '{}');""")
        self.execute("""CREATE TABLE topology (
            mac1 TEXT COLLATE "C" REFERENCES alldevices(mac),
            port1 INTEGER,
            mac2 TEXT COLLATE "C" REFERENCES alldevices(mac),
            port2 INTEGER,
            confirmed BOOLEAN,
            last_seen TIMESTAMP WITH TIME ZONE);""")
        self.execute("""CREATE TABLE images (
            fullname TEXT COLLATE "C" PRIMARY KEY);""")
        self.execute("""CREATE TABLE nodes (
            mac TEXT COLLATE "C" REFERENCES alldevices(mac),
            image TEXT COLLATE "C" REFERENCES images(fullname),
            model TEXT COLLATE "C");""")
        self.execute("""CREATE TABLE switches (
            mac TEXT COLLATE "C" REFERENCES alldevices(mac),
            model TEXT COLLATE "C");""")
        self.execute("""CREATE TABLE switchports (
            mac TEXT COLLATE "C" REFERENCES alldevices(mac),
            port INTEGER,
            name TEXT COLLATE "C",
            PRIMARY KEY (mac, port));""")
        self.execute("""CREATE TABLE alllogstreams (
            id SERIAL PRIMARY KEY,
            issuer_mac TEXT COLLATE "C" REFERENCES alldevices(mac),
            name TEXT COLLATE "C");""")
        self.execute("""CREATE TABLE alllogs (
            stream_id INTEGER REFERENCES logstreams(id),
            timestamp TIMESTAMP WITH TIME ZONE,
            line TEXT COLLATE "C");""")
        self.execute("""CREATE TABLE checkpoints (
            username TEXT COLLATE "C",
            timestamp TIMESTAMP,
            name TEXT COLLATE "C");""")
        self.execute("""CREATE TABLE poeoff (
            mac TEXT COLLATE "C" REFERENCES alldevices(mac),
            port INTEGER,
            reason TEXT COLLATE "C");""")
        # We have two different tables "vpnnodes" and "vpnauth"
        # because in the case of "walt device forget" we may want
        # to forget a vpn node, but still keep track of the auth data
        # in case we want to revoke it in the future.
        # The device is identified by either a corresponding entry in
        # table vpnnodes or a non-NULL device_label value,
        # depending on whether the device was forgotten or not.
        self.execute("""CREATE TABLE vpnauth (
            vpnmac TEXT COLLATE "C" PRIMARY KEY,
            pubkeycert TEXT COLLATE "C",
            certid TEXT COLLATE "C",
            device_label TEXT COLLATE "C",
            revoked BOOLEAN DEFAULT FALSE);""")
        self.execute("""CREATE TABLE vpnnodes (
            mac TEXT COLLATE "C" REFERENCES alldevices(mac),
            vpnmac TEXT COLLATE "C" REFERENCES vpnauth(vpnmac));""")

    def _migrate_v10_to_v11(self):
        # migration v10 -> v11
        # "devices" was a table, it must be renamed to "alldevices"
        # and "devices" will become a view on "alldevices".
        # The same applies to tables "logstreams" and "logs".
        # Table "alldevices" may contain rows with 'type' = 'deleted'
        # but those rows are excluded from the view.
        # Views 'logs' and 'logstreams' also exclude logging data
        # issued by devices with 'type' = 'deleted'.
        # This allows to handle deletion of logging data gradually
        # when forgetting a device or removing a virtual node.
        for view in ("devices", "logstreams", "logs"):
            tbl = f"all{view}"
            self.execute(f"ALTER TABLE {view} RENAME TO {tbl}")
        self._fix_collations()
        self._create_views()

    def _init_new_db(self):
        # first db initialization, create tables and views
        self._create_tables()
        self._create_views()

    def prepare(self):
        PostgresDB.prepare(self)  # parent method
        # create the db schema
        # tables
        if not self.table_exists("alldevices"):
            if self.table_exists("devices"):
                self._migrate_v10_to_v11()
            else:
                self._init_new_db()
        # indexes
        self.execute("""CREATE INDEX IF NOT EXISTS logs_timestamp_idx
                         ON alllogs ( timestamp );""")
        self.execute("""CREATE INDEX IF NOT EXISTS logs_stream_id_idx
                         ON alllogs ( stream_id );""")
        self.execute("""CREATE INDEX IF NOT EXISTS logstreams_issuer_mac_name_idx
                         ON alllogstreams ( issuer_mac, name );""")
        self.execute("""CREATE INDEX IF NOT EXISTS devices_ip_idx
                         ON alldevices ( ip );""")
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
        # in case the cleanup of removed devices was not fully completed
        # when the service last stopped, resume this process.
        self.plan_cleanup_deleted()
        # commit
        self.commit()

    def _fix_collations(self):
        # In older versions we were using the collation of the default locale
        # e.g., fr_FR.UTF8, so text comparison in postgresql worked as a human
        # would expect; for example: 'é' < 'f'. But this collation algorithm
        # is managed by libc and depends on the unicode standard, which
        # evolves, so in specific cases an OS upgrade could break our indexes.
        # We now specify COLLATE "C" on TEXT columns when creating the
        # database, in order to just compare text strings using their
        # underlying byte values.
        # In order to fix older WALT installations and converge to the new
        # schema, we will alter TEXT columns using the default collation
        # to use the "C" collation instead,  and rebuild the corresponding
        # indexes.
        sql_table_columns = """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE data_type = 'text'
              AND collation_name IS NULL
              AND table_schema = 'public'
        """
        db_indexes = self.execute(f"""
            WITH text_cols AS ({sql_table_columns})
            SELECT DISTINCT i.relname AS index_name
            FROM pg_index    ix
            JOIN pg_class    t ON t.oid        = ix.indrelid
            JOIN pg_class    i ON i.oid        = ix.indexrelid
            JOIN pg_attribute a ON a.attrelid = t.oid
                                AND a.attnum  = ANY (ix.indkey)
            JOIN text_cols  c ON c.table_name = t.relname
                              AND c.column_name = a.attname
        """)
        db_columns = self.execute(sql_table_columns)
        # fix TEXT columns with default collation to use "C" collation
        for col in db_columns:
            self.execute(f'''ALTER TABLE {col.table_name}
                             ALTER COLUMN {col.column_name}
                                 TYPE text COLLATE "C"''')
        # rebuild corresponding indexes
        for idx in db_indexes:
            self.execute(f'''REINDEX INDEX {idx.index_name}''')
        # also define a collation corresponding to the OS default,
        # for use in queries which need to print a result sorted
        # in the way the user would expect.
        os_lc_collate = self._detect_os_lc_collate()
        if "." in os_lc_collate:
            # pg_collation table has for instance "fr_FR.utf8",
            # not "fr_FR.UTF-8"
            base, codeset = os_lc_collate.split(".")
            codeset = codeset.lower().replace("-", "").replace("_", "")
            os_lc_collate = base + "." + codeset
        self.execute('CREATE COLLATION IF NOT EXISTS "os-default" '
                    f'FROM "{os_lc_collate}";')

    def _detect_os_lc_collate(self):
        saved_py_lc_collate = locale.setlocale(locale.LC_COLLATE)
        os_lc_collate = locale.setlocale(locale.LC_COLLATE, '')
        locale.setlocale(locale.LC_COLLATE, saved_py_lc_collate)
        return os_lc_collate

    def plan_cleanup_deleted(self):
        # schedule the progressive removal of devices previously deleted
        # (i.e., "forgotten" physical devices and removed virtual nodes).
        if self._cleaning_up_removed_devices:
            # A cleanup operation is still running after another device
            # was removed.
            # This existing process will handle both devices so there
            # is not need to plan anything here.
            return
        self._cleaning_up_removed_devices = True
        self.ev_loop.plan_event(ts=time(), target=self,
                                ev_type=EV_CLEANUP_DELETED)

    def _cleanup_deleted_step(self):
        # perform a bounded amount of work; if some work remains, plan
        # the next step a bit later so that the db process can handle
        # other requests in the meantime.
        work_remains = self._cleanup_deleted_chunk()
        if work_remains:
            self.ev_loop.plan_event(
                ts=time() + CLEANUP_DELETED_DELAY,
                target=self, ev_type=EV_CLEANUP_DELETED)
        else:
            self._cleaning_up_removed_devices = False

    def _cleanup_deleted_chunk(self):
        # return True if some work may still remain after this chunk,
        # False otherwise. Each deletion is committed right away, so
        # the whole cleanup procedure is resumable (it can be restarted
        # at any time, e.g. after a restart of the postgresql server).
        start = time()
        while time() - start < CLEANUP_DELETED_BUDGET:
            # find a deleted device which still has log streams
            rows = self.execute("""
                SELECT d.mac
                FROM alldevices d
                JOIN alllogstreams s ON s.issuer_mac = d.mac
                WHERE d.type = 'deleted'
                GROUP BY d.mac
                LIMIT 1""")
            if len(rows) == 0:
                # no deleted device with streams left: just remove the
                # remaining 'deleted' rows (devices without any logs)
                self.execute(
                    "DELETE FROM alldevices d WHERE d.type = 'deleted';")
                self.commit()
                return False
            # remove a bounded batch of logs for this device
            mac = rows[0].mac
            self.execute("""
                DELETE FROM alllogs
                WHERE ctid IN (
                    SELECT l.ctid
                    FROM alllogs l
                    JOIN alllogstreams s ON s.id = l.stream_id
                    WHERE s.issuer_mac = %s
                    LIMIT %s)""", (mac, CLEANUP_DELETED_BATCH))
            deleted_rows = self.c.rowcount
            if deleted_rows < CLEANUP_DELETED_BATCH:
                # this device has no more logs, remove its
                # streams and its device entry
                self.execute(
                    "DELETE FROM alllogstreams s WHERE s.issuer_mac = %s",
                    (mac,))
                self.execute(
                    "DELETE FROM alldevices d WHERE d.mac = %s", (mac,))
            self.commit()
        # we spent the whole time budget, more work may remain
        return True

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
            """SELECT mac FROM alldevices
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
                DELETE FROM alllogs l USING logstreams s
                    WHERE s.issuer_mac = %s AND l.stream_id = s.id;
                DELETE FROM alllogstreams s WHERE s.issuer_mac = %s;
                DELETE FROM alltopology t WHERE t.mac1 = %s;
                DELETE FROM alltopology t WHERE t.mac2 = %s;
                DELETE FROM allpoeoff po WHERE po.mac = %s;
                DELETE FROM alldevices d WHERE d.mac = %s;
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

    def table_exists(self, table_name):
        return self.select_unique(
            "pg_class",
            relname=table_name,
            relkind='r') is not None

    def view_exists(self, view_name):
        return self.select_unique(
            "pg_class",
            relname=view_name,
            relkind='v') is not None

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
        if ev_type == EV_AUTO_COMMIT:
            self.commit()
        elif ev_type == EV_CLEANUP_DELETED:
            self._cleanup_deleted_step()
        else:
            raise Exception(f"Unexpected planned event type: {ev_type}")

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
        sql = """
            UPDATE vpnauth va
            SET device_label = (
                SELECT 'forgotten device "' ||
                    d.name || '" mac=' || d.mac
                FROM devices d
                WHERE d.mac = %s
            )
            FROM vpnnodes vn
            WHERE va.vpnmac = vn.vpnmac
              AND vn.mac = %s;
            """
        # Removing all logging data issued by a device from the
        # database can be a heavy operation and block the db process
        # too long.
        # Instead, we just update the device type to 'deleted'
        # so that it is excluded from database views (devices,
        # logstreams, and logs) and the full db cleanup will be handled
        # gradually (see self.plan_cleanup_deleted() below).
        sql += "UPDATE alldevices SET type='deleted' WHERE mac = %s;"
        # For other tables it should be fast so we can proceed
        # right away.
        sql += """
            DELETE FROM nodes n WHERE n.mac = %s;
            DELETE FROM switchports sp WHERE sp.mac = %s;
            DELETE FROM switches s WHERE s.mac = %s;
            DELETE FROM topology t WHERE t.mac1 = %s OR t.mac2 = %s;
            DELETE FROM poeoff po WHERE po.mac = %s;
            DELETE FROM vpnnodes vn WHERE vn.mac = %s;
        """
        self.execute(sql, (mac,) * sql.count("%s"))
        self.commit()
        # schedule the gradual cleanup of this device's logs
        # (doing it all at once could block the process for a
        # long time).
        self.plan_cleanup_deleted()

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
