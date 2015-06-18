#!/usr/bin/env python

from walt.server.const import WALT_DBNAME, WALT_DBUSER
from walt.server.tools import columnate
import psycopg2, os, shlex
from psycopg2.extras import NamedTupleCursor
from subprocess import Popen, PIPE
from sys import stdout, stderr

QUOTE="'"

def quoted(string):
    s = str(string)
    if s == 'NULL':
        return s
    else:
        return QUOTE + s + QUOTE

class PostgresDB():

    def __init__(self):
        self.conn = None
        while self.conn == None:
            try:
                self.conn = psycopg2.connect(
                        database=WALT_DBNAME, user=WALT_DBUSER)
            except psycopg2.OperationalError:
                self.create_db_and_user()
        # allow name-based access to columns
        self.c = self.conn.cursor(cursor_factory = NamedTupleCursor)

    def __del__(self):
        self.conn.commit()
        self.c.close()
        self.conn.close()

    def create_db_and_user(self):
        # we must use the postgres admin user for this
        args = shlex.split('su -c psql -l postgres')
        popen = Popen(args, stdin=PIPE, stdout=stdout, stderr=stderr)
        popen.stdin.write('''
                CREATE USER %(user)s;
                ALTER ROLE %(user)s WITH CREATEDB;
                CREATE DATABASE %(db)s OWNER %(user)s;
                ''' % dict(user=WALT_DBUSER, db=WALT_DBNAME))
        popen.stdin.close()
        popen.wait()

    def commit(self):
        self.conn.commit()

    def execute(self, query):
        self.c.execute(query)
        return self.c

    # from a dictionary of the form <col_name> -> <value>
    # we want to filter-out keys that are not column names,
    # format the value for usage in an SQL statement,
    # and return (<col_name>, <value>) tuples.
    def get_tuples(self, table, dictionary):
        # retrieve fields names for this table 
        self.c.execute("SELECT * FROM %s LIMIT 0" % table)
        col_names = set(col_desc[0] for col_desc in self.c.description)

        res = {}
        for k in dictionary:
            # filter-out keys of dictionary that are not 
            # a column name
            if k not in col_names:
                continue

            # format the value appropriately for an SQL
            # statement
            value = dictionary[k]
            if value == None:
                value = 'NULL'
            else:
                value = quoted(value)

            # store in the result dict
            res[k] = value
        # we prefer a list of (k,v) items instead of
        # a dictionary, because in an insert query,
        # we need a list of keys and a list of values 
        # with the same ordering.
        return res.items()

    # allow statements like:
    # db.insert("network", ip=ip, switch_ip=swip)
    def insert(self, table, returning=None, **kwargs):
        # insert and return True or return False
        tuples = self.get_tuples(table, kwargs)
        sql = """INSERT INTO %s(%s)
                VALUES (%s)""" % (
                    table,
                    ','.join(t[0] for t in tuples),
                    ','.join(t[1] for t in tuples))
        if returning:
            sql += " RETURNING %s" % returning
        self.c.execute(sql + ';')
        if returning:
            return self.c.fetchone()[0]

    # allow statements like:
    # db.update("topology", "mac", switch_mac=swmac, switch_port=swport)
    def update(self, table, primary_key_name, **kwargs):
        tuples = self.get_tuples(table, kwargs)
        self.c.execute("""
                UPDATE %s 
                SET %s
                WHERE %s = %s;""" % (
                    table,
                    ','.join("%s = %s" % t for t in tuples),
                    primary_key_name,
                    quoted(kwargs[primary_key_name])))
        return self.c.rowcount  # number of rows updated

    # allow statements like:
    # mem_db.select("network", ip=ip)
    def select(self, table, **kwargs):
        constraints = [ "%s=%s" % t for t in \
                self.get_tuples(table, kwargs) ]
        if len(constraints) > 0:
            where_clause = "WHERE %s" % (
                ' AND '.join(constraints));
        else:
            where_clause = ""
        self.c.execute("SELECT * FROM %s %s;" % (
                    table, where_clause))
        return self.c.fetchall()

    # same as above but expect only one matching record
    # and return it.
    def select_unique(self, table, **kwargs):
        record_list = self.select(table, **kwargs)
        if len(record_list) == 0:
            return None
        else:
            return record_list[0]

    def pretty_printed_table(self, table):
        return self.pretty_printed_select("select * from %s;" % table)

    def pretty_printed_select(self, select_query):
        res = self.execute(select_query).fetchall()
        return columnate(res, header=res[0]._fields)

