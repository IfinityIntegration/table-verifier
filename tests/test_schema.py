import unittest
from db.schema_metadata import match_tables, shared_key
from utils.errors import ConfigurationError


class SchemaTests(unittest.TestCase):
    def test_pairing_and_missing(self):
        self.assertEqual(match_tables(['users', 'pg_only'], ['USERS', 'ORA_ONLY']),
                         ([('users', 'USERS')], ['pg_only'], ['ORA_ONLY']))
    def test_ambiguous_names(self):
        with self.assertRaises(ConfigurationError):
            match_tables(['users', 'USERS'], ['USERS'])
    def test_composite_keys(self):
        self.assertEqual(shared_key(['tenant', 'id'], ['ID', 'TENANT']), ['tenant', 'id'])
    def test_missing_or_different_keys(self):
        for pg, ora in [([], ['ID']), (['id'], []), (['id'], ['name'])]:
            with self.assertRaises(ConfigurationError):
                shared_key(pg, ora)

class SchemaRunnerTests(unittest.TestCase):
    def test_valid_and_skipped_tables_are_accounted_for(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock, patch
        from comparator.metadata import Column
        from comparator.schema_comparator import compare_schema
        client = MagicMock()
        client.__enter__.return_value = client
        client.get_columns.return_value = [Column('id', 'integer', False, 1)]
        client.fetch_batches.side_effect = lambda table, *args: (batch for batch in ([[(1,)]] if table == 'a' else []))
        with tempfile.TemporaryDirectory() as directory, \
             patch('comparator.schema_comparator.PostgresClient', return_value=client), \
             patch('comparator.schema_comparator.OracleClient', return_value=client), \
             patch('comparator.schema_comparator.list_tables', side_effect=[['a','b'], ['A','B']]), \
             patch('comparator.schema_comparator.primary_key', side_effect=[['id'], ['ID'], [], []]):
            result = compare_schema(Path(directory), {'schema':'public', 'database':'example_db'}, {'schema':'APP', 'username':'REPORT_USER'}, 10, workers=1)
            self.assertEqual(result, 1)
            logs = '\n'.join(p.read_text() for p in (Path(directory)/'logs').glob('*.log'))
            self.assertIn('NOT_COMPARED', logs)
            self.assertIn('COMPLETE', logs)
            self.assertIn('completed_table_totals', logs)
            reports = list((Path(directory)/'reports').glob('schema_issues_*.csv'))
            self.assertEqual(len(reports), 1)
            self.assertTrue(reports[0].name.startswith('schema_issues_REPORT_USER_'))
            self.assertIn('NOT_COMPARED', reports[0].read_text(encoding='utf-8-sig'))
            self.assertIn('MISSING_IN_ORACLE', reports[0].read_text(encoding='utf-8-sig'))
            self.assertNotIn('DIFFERENCE ', logs)

class ParallelTests(unittest.TestCase):
    def test_worker_connections_reused_and_reports_isolated(self):
        import threading
        import time
        import tempfile
        import json
        from pathlib import Path
        from unittest.mock import patch
        from comparator.metadata import Column
        from comparator.schema_comparator import compare_schema
        made = []
        class FakeClient:
            def __init__(self, config):
                self.config = config
                self.owner = None
                self.starts = 0
                self.closed = False
                made.append(self)
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
            def test_connection(self): pass
            def close(self): self.closed = True
            def begin_table(self):
                if self.owner is None: self.owner = threading.get_ident()
                assert self.owner == threading.get_ident()
                self.starts += 1
            def get_columns(self, table): return [Column('id', 'integer', False, 1)]
            def fetch_batches(self, *args):
                assert self.owner == threading.get_ident()
                time.sleep(0.02)
                yield [(1,)]
        with tempfile.TemporaryDirectory() as directory, \
             patch('comparator.schema_comparator.PostgresClient', FakeClient), \
             patch('comparator.schema_comparator.OracleClient', FakeClient), \
             patch('comparator.schema_comparator.list_tables', return_value=['a','b','c','d']), \
             patch('comparator.schema_comparator.primary_key', return_value=['id']):
            self.assertEqual(compare_schema(Path(directory), {'schema':'p'}, {'schema':'o'}, workers=2), 0)
            active = [c for c in made if c.starts]
            self.assertEqual(len(active), 4)
            self.assertEqual(sum(c.starts for c in active), 8)
            self.assertTrue(all(c.closed for c in made))
            self.assertEqual(len({c.owner for c in active}), 2)
            logs = list((Path(directory)/'logs').glob('*.log'))
            summaries = [json.loads(p.read_text().split('SUMMARY ')[-1]) for p in logs]
            master = next(s for s in summaries if s.get('comparison_scope') == 'schema')
            self.assertEqual(master['matched'], 4)
            self.assertEqual(len(master['table_results']), 4)

    def test_transaction_reset(self):
        from unittest.mock import MagicMock
        from db.oracle_client import OracleClient
        c = OracleClient({'schema':'APP'})
        connection = c.connection = MagicMock()
        c.begin_table()
        connection.rollback.assert_called_once()
        connection.cursor.return_value.__enter__.return_value.execute.assert_called_with('SET TRANSACTION READ ONLY')
