#!/usr/bin/env python
from walt.server.postgres import PostgresDB
from time import time

EV_AUTO_COMMIT              = 0
EV_AUTO_COMMIT_PERIOD       = 2

class ServerDB(PostgresDB):

    def __init__(self):
        # parent constructor
        PostgresDB.__init__(self)
        # create the db schema
        self.execute("""CREATE TABLE IF NOT EXISTS devices (
                    mac TEXT PRIMARY KEY,
                    ip TEXT,
                    name TEXT,
                    type TEXT,
                    virtual BOOLEAN DEFAULT FALSE);""")
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
                    booted BOOLEAN DEFAULT FALSE,
                    netsetup INTEGER DEFAULT 0);""")
        self.execute("""CREATE TABLE IF NOT EXISTS switches (
                    mac TEXT REFERENCES devices(mac),
                    model TEXT,
                    lldp_explore BOOLEAN DEFAULT FALSE,
                    poe_reboot_nodes BOOLEAN DEFAULT FALSE,
                    snmp_conf TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS config (
                    item TEXT PRIMARY KEY,
                    value TEXT);""")
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

    def get_logs(self, cursor_name, **kwargs):
        sql, args = self.format_logs_query('l.*', ordering='l.timestamp', **kwargs)
        cursor = self.server_cursors[cursor_name]
        cursor.execute(sql, args)
        return cursor

    def count_logs(self, **kwargs):
        sql, args = self.format_logs_query('count(*)', **kwargs)
        return self.execute(sql, args).fetchall()[0][0]

    def get_logstream_ids(self, senders):
        if senders == None:
            return self.select_no_fetch('logstreams')
        else:
            sender_names = '''('%s')''' % "','".join(senders)
            sql = """   SELECT s.*
                        FROM logstreams s, devices d
                        WHERE s.sender_mac = d.mac AND d.name IN %s;""" % sender_names
            return self.execute(sql)

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

    def get_config(self, item, default = None):
        res = self.select_unique("config", item=item)
        if res == None:
            if default == None:
                raise RuntimeError(\
                    "Failed get_config(): item not found and no default provided.")
            self.insert("config", item=item, value=default)
            self.commit()
            return default
        else:
            return res.value

    def set_config(self, item, value):
        res = self.select_unique("config", item=item)
        if res == None:
            self.insert("config", item=item, value=value)
        else:
            self.update("config", "item", item=item, value=value)
