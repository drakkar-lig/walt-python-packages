#!/usr/bin/env python

from plumbum.cmd import sqlite3 as sqlite3_sh
from walt.server.tools import eval_cmd
import sqlite3

QUOTE="'"
SQLITE_FORMATTING="""
.mode column
.headers on
.width 6 17 15 15 11
"""

def quoted(string):
    if string == 'NULL':
        return string
    else:
        return QUOTE + string + QUOTE

class MemoryDB():

    def __init__(self):
        self.c = sqlite3.connect(":memory:")

    def execute(self, query):
        self.c.execute(query)

    # allow statements like:
    # mem_db.try_insert("network", ip=ip, switch_ip=swip)
    # if a field of the network table is not specified, it
    # will receive the NULL value.
    def try_insert(self, table, **kwargs):
        # retrieve fields names for this table 
        table_desc = self.c.execute("PRAGMA table_info(%s)" % table)
        col_names = [ col_desc[1] for col_desc in table_desc ]

        # affect NULL to unspecified fields
        for col_name in col_names:
            if col_name not in kwargs:
                kwargs[col_name] = 'NULL'

        # insert and return True or return False
        try:
            self.c.execute("""INSERT INTO %s(%s)
                VALUES (%s);""" % (
                    table,
                    ','.join(col_names),
                    ','.join(quoted(str(kwargs[col_name])) for col_name in col_names)))
            return True
        except sqlite3.IntegrityError:
            return False

    def table_dump(self, table):
        # it seems there is no pretty printing available from the python module
        # so we use the sqlite3 shell command.
        # Its input will be:
        # - the formatting parameters
        # - a dump of the database 
        # - a select query to print the table contents
        db_dump = "\n".join(self.c.iterdump())
        query = "select * from %s;" % table
        result = eval_cmd(sqlite3_sh <<
                "%s\n%s\n%s" % (SQLITE_FORMATTING, db_dump, query))
        return result

