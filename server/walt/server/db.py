#!/usr/bin/env python

from walt.server.sqlite import SQLiteDB

class ServerDB(SQLiteDB):

    def __init__(self):
        # parent constructor
        SQLiteDB.__init__(self, '/var/lib/walt/server.db')
        # create the db schema
        self.execute("""CREATE TABLE IF NOT EXISTS devices (
                    mac TEXT PRIMARY KEY,
                    ip TEXT,
                    name TEXT,
                    reachable INTEGER,
                    type TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS topology (
                    mac TEXT PRIMARY KEY,
                    switch_mac TEXT,
                    switch_port INTEGER,
                    FOREIGN KEY(mac) REFERENCES devices(mac),
                    FOREIGN KEY(switch_mac) REFERENCES devices(mac));""")
        self.execute("""CREATE TABLE IF NOT EXISTS nodes (
                    mac TEXT PRIMARY KEY,
                    image TEXT,
                    FOREIGN KEY(mac) REFERENCES devices(mac));""")
        self.execute("""CREATE TABLE IF NOT EXISTS config (
                    item TEXT PRIMARY KEY,
                    value TEXT);""")
        self.execute("""CREATE TABLE IF NOT EXISTS logstreams (
                    id INTEGER PRIMARY KEY,
                    sender_mac TEXT,
                    name TEXT,
                    FOREIGN KEY(sender_mac) REFERENCES devices(mac));""")
        self.execute("""CREATE TABLE IF NOT EXISTS logs (
                    stream_id INTEGER,
                    timestamp TIMESTAMP,
                    line TEXT,
                    FOREIGN KEY(stream_id) REFERENCES logstreams(id));""")

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
            return res['value']

    def set_config(self, item, value):
        res = self.select_unique("config", item=item)
        if res == None:
            self.insert("config", item=item, value=value)
        else:
            self.update("config", "item", item=item, value=value)

