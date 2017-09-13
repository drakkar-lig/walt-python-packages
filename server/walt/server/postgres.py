#!/usr/bin/env python

from walt.server.const import WALT_DBNAME, WALT_DBUSER
from walt.server.tools import columnate
import psycopg2, shlex, uuid
from psycopg2.extras import NamedTupleCursor
from subprocess import Popen, PIPE
from sys import stderr

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
        self.server_cursors = {}

    def __del__(self):
        self.conn.commit()
        self.c.close()
        self.conn.close()

    def create_db_and_user(self):
        # we must use the postgres admin user for this
        args = shlex.split('su -c psql -l postgres')
        popen = Popen(args, stdin=PIPE, stdout=None, stderr=stderr)
        popen.stdin.write('''
                CREATE USER %(user)s;
                ALTER ROLE %(user)s WITH CREATEDB;
                CREATE DATABASE %(db)s OWNER %(user)s;
                ''' % dict(user=WALT_DBUSER, db=WALT_DBNAME))
        popen.stdin.close()
        popen.wait()

    def commit(self):
        self.conn.commit()

    def execute(self, query, query_args = None):
        self.c.execute(query, query_args)
        return self.c

    # with server cursors, the resultset is not sent all at once to the client.
    def create_server_cursor(self):
        name = str(uuid.uuid4())
        # we share a database connection, thus we have to create a cursor
        # WITH HOLD, otherwise any other thread issuing a commit would
        # cause the cursor to be discarded.
        self.server_cursors[name] = self.conn.cursor(
                                        name = name,
                                        cursor_factory = NamedTupleCursor,
                                        withhold = True)
        return name

    def delete_server_cursor(self, name):
        self.server_cursors[name].close()
        del self.server_cursors[name]

    def get_column_names(self, table):
        self.c.execute("SELECT * FROM %s LIMIT 0" % table)
        return tuple(col_desc[0] for col_desc in self.c.description)

    # from a dictionary of the form <col_name> -> <value>
    # we want to filter-out keys that are not column names,
    # and return ([<col_name>, ...], [<value>, ...]).
    def get_cols_and_values(self, table, dictionary):
        # retrieve fields names for this table 
        col_names = set(self.get_column_names(table))
        res = {}
        for k in dictionary:
            # filter-out keys of dictionary that are not 
            # a column name
            if k not in col_names:
                continue
            # store in the result dict
            res[k] = dictionary[k]
        # we prefer a tuple ([k,...],[v,...]) instead of
        # a dictionary, because in an insert query,
        # we need a list of keys and a list of values 
        # with the same ordering.
        items = res.items()
        return (list(t[0] for t in items),
                list(t[1] for t in items))

    # format a where clause with ANDs on the specified constraints
    def get_where_clause_from_constraints(self, constraints):
        if len(constraints) > 0:
            return "WHERE %s" % (' AND '.join(constraints));
        else:
            return ""

    # format a where clause with ANDs on the specified columns
    def get_where_clause_pattern(self, cols):
        constraints = [ "%s=%%s" % col for col in cols ]
        return self.get_where_clause_from_constraints(constraints)

    # allow statements like:
    # db.insert("network", ip=ip, switch_ip=swip)
    def insert(self, table, returning=None, **kwargs):
        # insert and return True or return False
        cols, values = self.get_cols_and_values(table, kwargs)
        sql = """INSERT INTO %s(%s)
                VALUES (%s)""" % (
                    table,
                    ','.join(cols),
                    ','.join(['%s'] * len(values)))
        if returning:
            sql += " RETURNING %s" % returning
        self.c.execute(sql + ';', tuple(values))
        if returning:
            return self.c.fetchone()[0]

    # allow statements like:
    # db.delete("topology", switch_mac=swmac, switch_port=swport)
    def delete(self, table, **kwargs):
        cols, values = self.get_cols_and_values(table, kwargs)
        where_clause = self.get_where_clause_pattern(cols)
        sql = "DELETE FROM %s %s;" % (table, where_clause)
        self.c.execute(sql, values)
        return self.c.rowcount  # number of rows deleted

    # allow statements like:
    # db.update("topology", "mac", switch_mac=swmac, switch_port=swport)
    def update(self, table, primary_key_name, **kwargs):
        cols, values = self.get_cols_and_values(table, kwargs)
        values.append(kwargs[primary_key_name])
        self.c.execute("""
                UPDATE %s 
                SET %s
                WHERE %s = %%s;""" % (
                    table,
                    ','.join("%s = %%s" % col for col in cols),
                    primary_key_name),
                    values)
        return self.c.rowcount  # number of rows updated

    def select_no_fetch(self, table, **kwargs):
        cols, values = self.get_cols_and_values(table, kwargs)
        where_clause = self.get_where_clause_pattern(cols)
        sql = "SELECT * FROM %s %s;" % (table, where_clause)
        self.c.execute(sql, values)
        return self.c

    # allow statements like:
    # mem_db.select("network", ip=ip)
    def select(self, table, **kwargs):
        return self.select_no_fetch(table, **kwargs).fetchall()

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

    def pretty_printed_select(self, *args):
        self.execute(*args)
        col_names = [col_desc[0] for col_desc in self.c.description]
        return columnate(self.c.fetchall(), header=col_names)

    def pretty_printed_resultset(self, res):
        if len(res) == 0:
            raise Exception('pretty_printed_resultset() does not work if resultset is empty!')
        return columnate(res, header=res[0]._fields)

