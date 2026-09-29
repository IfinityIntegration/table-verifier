import unittest
from unittest.mock import MagicMock
from comparator.metadata import Column, ComparisonConfig, build_plan
from db.postgres_client import PostgresClient
from db.oracle_client import OracleClient
from utils.errors import ConfigurationError, DatabaseError


def columns(*names):
    return [Column(n, 'integer', False, i) for i, n in enumerate(names, 1)]


class MetadataTests(unittest.TestCase):
    def config(self, **kwargs):
        return ComparisonConfig('a', 'B', **({'keys': ['id']} | kwargs))

    def test_composite_and_differences(self):
        plan = build_plan(self.config(keys=['tenant', 'id'], ignore_columns=['skip']),
                          columns('id', 'tenant', 'skip', 'pg'), columns('ID', 'TENANT', 'SKIP', 'ORA'))
        self.assertEqual(plan.postgres_select, ('tenant', 'id'))
        self.assertEqual(plan.oracle_select, ('TENANT', 'ID'))
        self.assertEqual(plan.postgres_only, ('pg',))
        self.assertEqual(plan.oracle_only, ('ORA',))
        self.assertEqual(len(plan.common), 3)

    def test_explicit_selection_includes_key(self):
        plan = build_plan(self.config(columns=['name']), columns('id', 'name', 'other'), columns('ID', 'NAME'))
        self.assertEqual(plan.postgres_select, ('id', 'name'))

    def test_invalid_plans(self):
        for config, pg, ora in [
            (self.config(), columns('id'), columns('other')),
            (self.config(ignore_columns=['id']), columns('id'), columns('ID')),
            (self.config(), columns('id', 'ID'), columns('ID')),
            (self.config(columns=['absent']), columns('id'), columns('ID')),
            (self.config(ignore_columns=['typo']), columns('id'), columns('ID')),
            (self.config(columns=['name'], ignore_columns=['name']), columns('id', 'name'), columns('ID', 'NAME')),
        ]:
            with self.subTest(config=config), self.assertRaises(ConfigurationError):
                build_plan(config, pg, ora)

    def test_invalid_config(self):
        for kwargs in ({'keys': []}, {'keys': 'id'}, {'keys': ['id', 'ID']}, {'batch_size': 0}, {'batch_size': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConfigurationError):
                self.config(**kwargs)


class ClientTests(unittest.TestCase):
    def client(self, cls=PostgresClient):
        client = cls({'schema': 'public'})
        client.connection = MagicMock()
        return client

    def test_identifier_injection_quoted(self):
        for cls in (PostgresClient, OracleClient):
            query = self.client(cls).build_select('x"; DROP TABLE users; --', ['a"b'])
            self.assertEqual(query, 'SELECT "a""b" FROM "public"."x""; DROP TABLE users; --"')

    def test_metadata_parameters_and_types(self):
        for cls in (PostgresClient, OracleClient):
            client = self.client(cls)
            cursor = client.connection.cursor.return_value.__enter__.return_value
            cursor.fetchall.side_effect = [[(1,)], [('id', 'integer', 'NO', 1)]]
            result = client.get_columns('table')
            self.assertEqual(result, [Column('id', 'integer', False, 1)])
            self.assertEqual(cursor.execute.call_args.args[1], client._params('table'))

    def test_missing_table(self):
        client = self.client()
        client.connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []
        with self.assertRaises(ConfigurationError):
            client.get_columns('absent')

    def test_bounded_fetch_and_cleanup(self):
        for cls in (PostgresClient, OracleClient):
            client = self.client(cls)
            manager = client.connection.cursor.return_value
            cursor = manager.__enter__.return_value
            cursor.fetchmany.side_effect = [[(1,)], [(2,)], []]
            self.assertEqual(list(client.fetch_batches('table', ['id'], 2)), [[(1,)], [(2,)]])
            self.assertEqual(cursor.fetchmany.call_count, 3)
            cursor.fetchmany.assert_called_with(2)
            cursor.fetchall.assert_not_called()
            manager.__exit__.assert_called_once()
            if cls is PostgresClient:
                self.assertIn('name', client.connection.cursor.call_args.kwargs)

    def test_early_close(self):
        client = self.client()
        manager = client.connection.cursor.return_value
        manager.__enter__.return_value.fetchmany.return_value = [(1,)]
        batches = client.fetch_batches('table', ['id'])
        next(batches)
        batches.close()
        manager.__exit__.assert_called_once()

    def test_context_close_and_sanitized_error(self):
        client = self.client()
        connection = client.connection
        with client:
            pass
        client.close()
        connection.close.assert_called_once()
        client = self.client()
        client.connection.cursor.side_effect = RuntimeError('secret password')
        with self.assertRaises(DatabaseError) as raised:
            client.test_connection()
        self.assertNotIn('secret', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
