import tempfile
import unittest
from comparator.batching import choose_batch_size
from comparator.metadata import Column, ComparisonConfig
from comparator.reporting import ReportRun
from utils.errors import ConfigurationError


class BatchTests(unittest.TestCase):
    def test_small_columns_keep_requested_batch(self):
        self.assertEqual(choose_batch_size(10000, [Column('id','integer',False,1)], [], ['id']), (10000, []))

    def test_large_type_on_either_side_caps_both_streams(self):
        for kind in ('BLOB','CLOB','NCLOB','bytea','text','jsonb','XMLTYPE'):
            with self.subTest(kind=kind):
                self.assertEqual(choose_batch_size(10000, [], [Column('DATA',kind,True,2)], ['data']), (100, ['data']))

    def test_ignored_large_columns_do_not_reduce_batch(self):
        self.assertEqual(choose_batch_size(10000, [Column('data','bytea',True,2)], [], ['id']), (10000, []))

    def test_preserves_smaller_request_and_custom_cap(self):
        columns = [Column('data','blob',True,1)]
        self.assertEqual(choose_batch_size(20, columns, [], ['data'])[0],20)
        self.assertEqual(choose_batch_size(10000, columns, [], ['data'], 250)[0],250)
        with self.assertRaises(ConfigurationError):
            ComparisonConfig('a','b',['id'],large_value_batch_size=0)

    def test_csv_differences_are_not_duplicated_in_log(self):
        with tempfile.TemporaryDirectory() as directory:
            report = ReportRun(directory, directory)
            report.emit({'status':'MISSING_IN_ORACLE','primary_key':[5]})
            report.finish()
            self.assertNotIn('DIFFERENCE', report.path.read_text())
            self.assertIn('MISSING_IN_ORACLE', report.csv_path.read_text(encoding='utf-8-sig'))
            self.assertIn('SUMMARY', report.path.read_text())
