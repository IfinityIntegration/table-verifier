import logging
from time import perf_counter
from uuid import uuid4
from comparator.metadata import Column, identifier
from utils.errors import ConfigurationError, DatabaseError

LOG = logging.getLogger(__name__)


class BaseClient:
    side = ''
    probe = 'SELECT 1'

    def __init__(self, config):
        self.config = dict(config)
        self.connection = None
        identifier(self.config['schema'])

    def connect(self):
        if self.connection is None:
            LOG.info('%s connecting', self.side)
            try:
                self.connection = self._connect()
            except Exception:
                LOG.error('%s connection failed', self.side)
                raise DatabaseError(f'{self.side} connection failed; check credentials, driver installation and network') from None
            LOG.info('%s connected', self.side)
        return self.connection

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
                LOG.debug('%s connection closed', self.side)
            except Exception:
                raise DatabaseError(f'{self.side} connection could not be closed') from None

    def begin_table(self):
        """Reuse the session, never the previous table's transaction."""
        connection = self.connect()
        try:
            connection.rollback()
            if self.side == 'Oracle':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION READ ONLY')
        except Exception:
            self.close()
            raise DatabaseError(f'{self.side} transaction reset failed') from None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self.close()
        except DatabaseError:
            if exc_type is None:
                raise
            LOG.error('%s cleanup failed', self.side)

    def _query(self, sql, parameters=None):
        try:
            with self.connect().cursor() as cursor:
                cursor.execute(sql, parameters)
                return cursor.fetchall()  # Metadata/probe only, never table data.
        except DatabaseError:
            raise
        except Exception:
            raise DatabaseError(f'{self.side} metadata query failed; check permissions and configuration') from None

    def test_connection(self):
        if not self._query(self.probe):
            raise DatabaseError(f'{self.side} connection test returned no result')
        LOG.info('%s connection test passed', self.side)
        return True

    def get_columns(self, table):
        identifier(table)
        if not self.table_exists(table):
            raise ConfigurationError(f'{self.side} table not found or not accessible: {self.config["schema"]}.{table}')
        rows = self._query(self.columns_sql, self._params(table))
        if not rows:
            raise ConfigurationError(f'{self.side} table has no accessible columns')
        return [Column(name, kind, nullable == 'YES' or nullable == 'Y', position)
                for name, kind, nullable, position in rows]

    def table_exists(self, table):
        identifier(table)
        return bool(self._query(self.exists_sql, self._params(table)))

    def build_select(self, table, columns, order_by=()):
        if not columns or isinstance(columns, str):
            raise ConfigurationError('SELECT requires a sequence of column names')
        query = 'SELECT ' + ', '.join(identifier(c) for c in columns) + ' FROM ' + identifier(self.config['schema']) + '.' + identifier(table)
        if order_by:
            if isinstance(order_by, str) or any(c not in columns for c in order_by):
                raise ConfigurationError('Sort keys must be selected column names')
            query += ' ORDER BY ' + ', '.join(identifier(c) for c in order_by)
        return query

    def fetch_batches(self, table, columns, batch_size=10000, order_by=()):
        """Consume within client context; close generator if stopping early."""
        if type(batch_size) is not int or not 1 <= batch_size <= 100000:
            raise ConfigurationError('batch_size must be between 1 and 100000')
        sql = self.build_select(table, columns, order_by)
        try:
            connection = self.connect()
            cursor_args = {'name': 'compare_' + uuid4().hex} if self.side == 'PostgreSQL' else {}
            with connection.cursor(**cursor_args) as cursor:
                cursor.arraysize = batch_size
                LOG.info('%s table=%s executing ordered SELECT', self.side, table)
                print(f'  {self.side}: starting read of {table}', flush=True)
                started = perf_counter()
                cursor.execute(sql)
                LOG.info('%s SELECT ready in %.3fs', self.side, perf_counter() - started)
                processed = 0
                while True:
                    LOG.info('%s fetching next batch size=%d total_fetched=%d', self.side, batch_size, processed)
                    started = perf_counter()
                    rows = cursor.fetchmany(batch_size)
                    LOG.info('%s batch received rows=%d duration=%.3fs', self.side, len(rows), perf_counter() - started)
                    if not rows:
                        break
                    processed += len(rows)
                    print(f'  {self.side}: {processed:,} rows fetched', flush=True)
                    LOG.debug('%s batch fetched=%d total_fetched=%d', self.side, len(rows), processed)
                    yield rows
        except DatabaseError:
            raise
        except Exception:
            raise DatabaseError(f'{self.side} batch fetch failed; check table access and selected columns') from None
