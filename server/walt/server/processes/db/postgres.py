import shlex
import uuid
from subprocess import PIPE, Popen
from sys import stderr

import psycopg2
from psycopg2.extras import NamedTupleCursor
from walt.common.formatting import columnate
from walt.server.const import WALT_DBNAME, WALT_DBUSER
from walt.server.tools import SerializableNT, build_named_tuple_cls


# we wrap database record objects otherwise they cannot be pickled
class DBRecord(SerializableNT):
    pass


class DBRecordSet:
    def __init__(self, records=None):
        self.records = records

    def __getstate__(self):
        return [row._asdict() for row in self.records]

    def __setstate__(self, dict_records):
        if len(dict_records) == 0:
            self.records = []
        else:
            nt_cls = build_named_tuple_cls(dict_records[0])
            self.records = [nt_cls(**row) for row in dict_records]

    def __iter__(self):
        return iter(self.records)

    def __len__(self):
        return len(self.records)

    def __getitem__(self, i):
        return self.records[i]


class PostgresDB:
    def __init__(self):
        self.conn, self.c = None, None
        self.server_cursors = {}
        self.schema_cache = {}

    def prepare(self):
        try:
            # Do catch exception here to create DB and users if there does not exist
            self.conn = psycopg2.connect(database=WALT_DBNAME, user=WALT_DBUSER)
        except psycopg2.OperationalError:
            self.create_db_and_user()
            # Do not catch any exception here to let the user know if something
            # happens bad
            self.conn = psycopg2.connect(database=WALT_DBNAME, user=WALT_DBUSER)
        # allow name-based access to columns
        self.c = self.conn.cursor(cursor_factory=NamedTupleCursor)

    def __del__(self):
        if self.conn is not None:
            self.conn.commit()
            self.c.close()
            self.conn.close()
            self.conn, self.c = None, None

    def create_db_and_user(self):
        # we must use the postgres admin user for this
        args = shlex.split("su -c psql -l postgres")
        popen = Popen(args, stdin=PIPE, stdout=None, stderr=stderr)
        popen.stdin.write(("""
                CREATE USER %(user)s;
                ALTER ROLE %(user)s WITH CREATEDB;
                CREATE DATABASE %(db)s OWNER %(user)s;
                """ % dict(user=WALT_DBUSER, db=WALT_DBNAME)).encode("ascii"))
        popen.stdin.close()
        popen.wait()

    def commit(self):
        self.conn.commit()

    def execute(self, query, query_args=None):
        self.c.execute(query, query_args)
        if self.c.description is None:  # it was not a select query
            return None
        return DBRecordSet(self.c.fetchall())

    # with server cursors, the resultset is not sent all at once to the client.
    def create_server_cursor(self, sql, args):
        name = str(uuid.uuid4())
        # we share a database connection, thus we have to create a cursor
        # WITH HOLD, otherwise any other process issuing a commit would
        # cause the cursor to be discarded.
        cursor = self.conn.cursor(
            name=name, cursor_factory=NamedTupleCursor, withhold=True
        )
        cursor.execute(sql, args)
        self.server_cursors[name] = cursor
        return name

    def step_server_cursor(self, name):
        row = self.server_cursors[name].fetchone()
        if row is None:
            return None
        else:
            return DBRecord(row)

    def delete_server_cursor(self, name):
        self.server_cursors[name].close()
        del self.server_cursors[name]

    def get_column_names(self, table):
        res = self.schema_cache.get(table)
        if res is None:
            self.c.execute("SELECT * FROM %s LIMIT 0" % table)
            res = tuple(col_desc[0] for col_desc in self.c.description)
            self.schema_cache[table] = res
        return res

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
        items = list(res.items())
        return (list(t[0] for t in items), list(t[1] for t in items))

    # format a where clause with ANDs on the specified constraints
    def get_where_clause_from_constraints(self, constraints):
        if len(constraints) > 0:
            return "WHERE %s" % " AND ".join(constraints)
        else:
            return ""

    # format a where clause with ANDs on the specified columns
    def get_where_clause_pattern(self, cols):
        constraints = ["%s=%%s" % col for col in cols]
        return self.get_where_clause_from_constraints(constraints)

    def get_insert_cols_and_values(self, table, rows_kwargs):
        values_formats = []
        all_values = []
        for kwargs in rows_kwargs:
            cols, values = self.get_cols_and_values(table, kwargs)
            values_format = "(" + ",".join(["%s"] * len(values)) + ")"
            values_formats.append(values_format)
            all_values.extend(values)
        return ",".join(cols), ",".join(values_formats), tuple(all_values)

    # allow statements like:
    # db.insert("network", ip=ip, switch_ip=swip)
    def insert(self, table, returning=None, **kwargs):
        return self.insert_multiple(table, [kwargs], returning=returning)

    # insert multiple rows at once
    def insert_multiple(
        self, table, rows_kwargs, returning=None, bypass_conflicting=False
    ):
        cols, formats, values = self.get_insert_cols_and_values(table, rows_kwargs)
        sql = """INSERT INTO %s(%s)
                VALUES %s""" % (
            table,
            cols,
            formats,
        )
        if bypass_conflicting:
            sql += " ON CONFLICT DO NOTHING"
        if returning:
            sql += " RETURNING %s" % returning
        self.c.execute(sql + ";", values)
        if returning:
            return self.c.fetchone()[0]

    # allow statements like:
    # db.delete("topology", switch_mac=swmac, switch_port=swport)
    def delete(self, table, **kwargs):
        """Delete entries from a table matching given fields"""
        cols, values = self.get_cols_and_values(table, kwargs)
        where_clause = self.get_where_clause_pattern(cols)
        sql = "DELETE FROM %s %s;" % (table, where_clause)
        self.c.execute(sql, values)
        return self.c.rowcount  # number of rows deleted

    # allow statements like:
    # db.update("topology", "mac", switch_mac=swmac, switch_port=swport)
    def update(self, table, primary_key_name, **kwargs):
        cols, values = self.get_cols_and_values(table, kwargs)
        if len(cols) > 1:  # if updating at least one field (pk counts as 1 in cols)
            values.append(kwargs[primary_key_name])
            self.c.execute(
                """
                UPDATE %s
                SET %s
                WHERE %s = %%s;"""
                % (table, ",".join("%s = %%s" % col for col in cols), primary_key_name),
                values,
            )
            return self.c.rowcount  # number of rows updated
        else:
            return 0

    # caution when calling select_no_fetch() not to let the
    # returned cursor leave db process
    def select_no_fetch(self, table, **kwargs):
        cols, values = self.get_cols_and_values(table, kwargs)
        where_clause = self.get_where_clause_pattern(cols)
        sql = "SELECT * FROM %s %s;" % (table, where_clause)
        self.c.execute(sql, values)
        return self.c

    # allow statements like:
    # mem_db.select("network", ip=ip)
    def select(self, table, **kwargs):
        return DBRecordSet(self.select_no_fetch(table, **kwargs).fetchall())

    # same as above but expect only one matching record
    # and return it.
    def select_unique(self, table, **kwargs):
        record_list = self.select(table, **kwargs)
        if len(record_list) == 0:
            return None
        else:
            return DBRecord(record_list[0])

    def pretty_printed_table(self, table):
        return self.pretty_printed_select("select * from %s;" % table)

    def pretty_printed_select(self, *args):
        self.c.execute(*args)
        col_names = [col_desc[0] for col_desc in self.c.description]
        return columnate(self.c.fetchall(), header=col_names)

    def pretty_print_select_info(self, *args):
        self.c.execute(*args)
        col_names = [col_desc[0] for col_desc in self.c.description]
        return DBRecordSet(self.c.fetchall()), col_names

    def pretty_printed_resultset(self, res):
        if len(res) == 0:
            raise Exception(
                "pretty_printed_resultset() does not work if resultset is empty!"
            )
        return columnate(res, header=res[0]._fields)
