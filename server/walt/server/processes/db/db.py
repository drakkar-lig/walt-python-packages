import re
import pickle
from walt.server import const
from walt.common.tools import get_mac_address
from walt.server.tools import get_server_ip
from walt.server.processes.db.postgres import PostgresDB
from time import time

EV_AUTO_COMMIT              = 0
EV_AUTO_COMMIT_PERIOD       = 2

class ServerDB(PostgresDB):

    def __init__(self):
        # parent constructor
        PostgresDB.__init__(self)
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
                    fullname TEXT PRIMARY KEY,
                    ready BOOLEAN);""")
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
                    sender_mac TEXT REFERENCES devices(mac),
                    name TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS logs (
                    stream_id INTEGER REFERENCES logstreams(id),
                    timestamp TIMESTAMP,
                    line TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                    username TEXT,
                    timestamp TIMESTAMP,
                    name TEXT);""")
        # indexes
        self.execute("""CREATE INDEX IF NOT EXISTS logs_timestamp_idx
                         ON logs ( timestamp );""")
        self.execute("""CREATE INDEX IF NOT EXISTS logstreams_sender_mac_name_idx
                         ON logstreams ( sender_mac, name );""")
        self.execute("""CREATE INDEX IF NOT EXISTS devices_ip_idx
                         ON devices ( ip );""")
        self.execute("""CREATE INDEX IF NOT EXISTS checkpoints_username_idx
                         ON checkpoints ( username );""")
        # migration v4 -> v5
        if not self.column_exists('devices', 'conf'):
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
                                    '{"snmp.version": ' || (s.snmp_conf::jsonb->'version')::text || ',' ||
                                    ' "snmp.community": ' || (s.snmp_conf::jsonb->'community')::text || '}'
                                )::jsonb
                            FROM switches s
                            WHERE s.mac = d.mac AND s.snmp_conf IS NOT NULL;""")
            self.execute("""ALTER TABLE switches
                            DROP COLUMN snmp_conf,
                            DROP COLUMN lldp_explore,
                            DROP COLUMN poe_reboot_nodes;""")
            self.execute("""UPDATE devices d
                            SET conf = conf || ('{"netsetup":' || n.netsetup || '}')::jsonb
                            FROM nodes n
                            WHERE n.mac = d.mac;""")
            self.execute("""ALTER TABLE nodes
                            DROP COLUMN netsetup;""")
            # When migrating to v5, walt image storage management moves from docker to podman.
            # In order to avoid duplicating many old and unused images to podman storage, we
            # remove the reference of unused images from database.
            self.execute("""DELETE FROM images
                            WHERE fullname NOT IN (
                                SELECT DISTINCT image FROM nodes
                            );""")
        # fix server entry
        self.fix_server_device_entry()
        # commit
        self.commit()

    def fix_server_device_entry(self):
        server_ip = get_server_ip()
        server_mac = get_mac_address(const.WALT_INTF)
        server_entry = self.select_unique('devices', mac=server_mac)
        if server_entry is None:
            self.insert('devices', mac=server_mac, ip=server_ip,
                                   name='walt-server', type='server')
        else:
            self.update('devices', 'mac', mac=server_mac, ip=server_ip,
                                   name='walt-server', type='server')
        # ensure wrong entries were not left out by previous versions
        # of walt server code
        wrong_entries = self.execute(
                """SELECT mac FROM devices
                   WHERE mac != %s
                     AND (  ip = %s OR
                            type = 'server' OR
                            name = 'walt-server' );
                """, (server_mac, server_ip))
        for entry in wrong_entries:
            self.delete('topology', mac1=entry.mac)
            self.delete('topology', mac2=entry.mac)
            self.delete('devices', mac=entry.mac)

    def column_exists(self, table_name, column_name):
        col_info = self.select_unique(
                            'information_schema.columns',
                            table_schema='public',
                            table_name=table_name,
                            column_name=column_name)
        return col_info is not None

    # Some types of events are numerous and commiting the
    # database each time would be costly.
    # That's why we auto-commit every few seconds.
    def plan_auto_commit(self, ev_loop):
        ev_loop.plan_event(
            ts = time(),
            target = self,
            repeat_delay = EV_AUTO_COMMIT_PERIOD,
            ev_type = EV_AUTO_COMMIT
        )

    def handle_planned_event(self, ev_type):
        assert(ev_type == EV_AUTO_COMMIT)
        self.commit()

    def create_server_logs_cursor(self, **kwargs):
        sql, args = self.format_logs_query('l.*', ordering='l.timestamp', **kwargs)
        return self.create_server_cursor(sql, args)

    def get_logstream_ids(self, senders):
        if senders == None:
            return self.select_no_fetch('logstreams')
        else:
            sender_names = '''('%s')''' % "','".join(senders)
            sql = """   SELECT s.*
                        FROM logstreams s, devices d
                        WHERE s.sender_mac = d.mac AND d.name IN %s;""" % sender_names
            return self.execute(sql)

    def count_logs(self, history, streams = None, senders = None, **kwargs):
        unpickled_history = (pickle.loads(e) if e else None for e in history)
        if streams:
            # compute streams ids whose name match the regular expression
            stream_ids = []
            streams_re = re.compile(streams)
            for row in self.get_logstream_ids(senders):
                matches = streams_re.findall(row.name)
                if len(matches) > 0:
                    stream_ids.append(str(row.id))
            if len(stream_ids) == 0:
                return 0    # no streams => no logs
            # we can release the constraint on senders since we restrict to
            # their logstreams (cf. stream_ids variable we just computed)
            senders = None
        else:
            stream_ids = None
        sql, args = self.format_logs_query('count(*)',
                                           history = unpickled_history,
                                           senders = senders,
                                           stream_ids = stream_ids,
                                           **kwargs)
        return self.execute(sql, args)[0][0]

    def format_logs_query(self, projections, ordering=None, \
                    senders=None, history=(None,None), stream_ids=None, **kwargs):
        args = []
        constraints = [ 's.sender_mac = d.mac', 'l.stream_id = s.id' ]
        if stream_ids:
            stream_ids_sql = '''(%s)''' % ",".join(
                str(stream_id) for stream_id in stream_ids)
            constraints.append('s.id IN %s' % stream_ids_sql)
        if senders:
            sender_names = '''('%s')''' % "','".join(senders)
            constraints.append('d.name IN %s' % sender_names)
        start, end = history
        if start:
            constraints.append('l.timestamp > %s')
            args.append(start)
        if end:
            constraints.append('l.timestamp < %s')
            args.append(end)
        where_clause = self.get_where_clause_from_constraints(constraints)
        if ordering:
            ordering = 'order by ' + ordering
        else:
            ordering = ''
        return ("SELECT %s FROM devices d, logstreams s, logs l %s %s;" % \
                                (projections, where_clause, ordering), args)

    def forget_device(self, dev_name):
        self.execute("""
            DELETE FROM logs l USING devices d, logstreams s
                WHERE d.name = %s AND s.sender_mac = d.mac AND l.stream_id = s.id;
            DELETE FROM logstreams s USING devices d WHERE d.name = %s AND s.sender_mac = d.mac;
            DELETE FROM nodes n USING devices d WHERE d.name = %s AND d.mac = n.mac;
            DELETE FROM switches s USING devices d WHERE d.name = %s AND d.mac = s.mac;
            DELETE FROM topology t USING devices d WHERE d.name = %s AND d.mac = t.mac1;
            DELETE FROM topology t USING devices d WHERE d.name = %s AND d.mac = t.mac2;
            DELETE FROM devices d WHERE d.name = %s;
        """,  (dev_name,)*7)
        self.commit()
