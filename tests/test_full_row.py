import csv
import tempfile
import unittest
from comparator.reporting import ReportRun, run_comparison


class FullRowTests(unittest.TestCase):
    def test_changed_name_and_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            report = ReportRun(directory, directory)
            result = run_comparison([[(1, 'sanuth', 'hello'), (2, 'same', 'text ')]],
                                    [[(1, 'sssanuth', b'hello'), (2, 'same', b'text')]],
                                    ['id', 'name', 'parameters'], 1, report)
            report.finish()
            self.assertEqual(result.value_mismatches, 2)
            with report.csv_path.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r['column'] for r in rows], ['name', 'parameters'])
            self.assertIn('sanuth', rows[0]['postgres_value'])
            self.assertIn('sssanuth', rows[0]['oracle_value'])

    def test_whitespace_and_invalid_binary(self):
        from comparator.value_normalizer import values_equal
        self.assertFalse(values_equal('a', 'a '))
        self.assertFalse(values_equal('a', b'\xff'))
        self.assertTrue(values_equal('hello', b'hello'))
        self.assertFalse(values_equal(None, ''))
