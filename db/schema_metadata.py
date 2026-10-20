"""Schema discovery; only metadata is collected into memory."""
from utils.errors import ConfigurationError


def list_tables(client):
    if client.side == 'PostgreSQL':
        return [r[0] for r in client._query("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name", (client.config['schema'],))]
    return [r[0] for r in client._query("SELECT table_name FROM all_tables WHERE owner=:owner AND nested='NO' AND secondary='N' ORDER BY table_name", {'owner': client.config['schema']})]


def primary_key(client, table):
    if client.side == 'PostgreSQL':
        return [r[0] for r in client._query("""SELECT a.attname FROM pg_index i
            JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(num,pos)
            JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=k.num
            WHERE i.indisprimary AND i.indisvalid AND n.nspname=%s AND t.relname=%s
            ORDER BY k.pos""", (client.config['schema'], table))]
    return [r[0] for r in client._query("""SELECT cc.column_name FROM all_constraints c
        JOIN all_cons_columns cc ON c.owner=cc.owner AND c.constraint_name=cc.constraint_name
        WHERE c.constraint_type='P' AND c.status='ENABLED' AND c.validated='VALIDATED'
        AND c.owner=:owner AND c.table_name=:tab ORDER BY cc.position""",
        {'owner': client.config['schema'], 'tab': table})]


def match_tables(pg_names, oracle_names):
    def index(names):
        result = {}
        for name in names:
            key = name.casefold()
            if key in result:
                raise ConfigurationError('Ambiguous case-insensitive table names in schema')
            result[key] = name
        return result
    pg, ora = index(pg_names), index(oracle_names)
    return ([(pg[k], ora[k]) for k in sorted(pg.keys() & ora.keys())],
            [pg[k] for k in sorted(pg.keys() - ora.keys())],
            [ora[k] for k in sorted(ora.keys() - pg.keys())])


def shared_key(pg_keys, ora_keys):
    if not pg_keys or not ora_keys:
        raise ConfigurationError('No primary key on one or both tables; manual unique-key configuration required')
    if {k.casefold() for k in pg_keys} != {k.casefold() for k in ora_keys}:
        raise ConfigurationError('Primary-key columns differ between databases')
    return pg_keys
