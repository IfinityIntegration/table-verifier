from db.base_client import BaseClient


class PostgresClient(BaseClient):
    # Only usable, non-partial, non-expression ascending B-tree key columns.
    index_sql = """SELECT idx.relname, a.attname, k.ordinality
        FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
        JOIN pg_catalog.pg_am am ON am.oid = idx.relam
        CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum, ordinality)
        JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
        WHERE n.nspname = %s AND t.relname = %s AND am.amname = 'btree'
          AND i.indisvalid AND i.indisready AND i.indpred IS NULL AND i.indexprs IS NULL
          AND k.ordinality <= i.indnkeyatts
          AND i.indoption[k.ordinality::int - 1] = 0
        ORDER BY idx.relname, k.ordinality"""
    side = 'PostgreSQL'
    exists_sql = """SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s AND table_type = 'BASE TABLE'"""
    columns_sql = """SELECT column_name, data_type, is_nullable, ordinal_position
        FROM information_schema.columns WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position"""

    def _params(self, table):
        return (self.config['schema'], table)

    def _connect(self):
        import psycopg
        cfg = self.config
        connection = psycopg.connect(host=cfg['host'], port=cfg['port'], dbname=cfg['database'],
                                     user=cfg['username'], password=cfg['password'], connect_timeout=15)
        connection.read_only = True
        return connection
