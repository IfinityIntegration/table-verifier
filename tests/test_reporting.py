import json
import tempfile
import unittest
from pathlib import Path
from comparator.reporting import ReportRun, run_comparison


class ReportTests(unittest.TestCase):
    def test_one_log_with_all_differences_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            report = ReportRun(directory)
            run_comparison([[(1, 'a'), (2, 'b'), (4, 'd')]], [[(1, 'a'), (2, 'B'), (3, 'c')]], ['id', 'name'], 1, report)
            report.finish()
            text = report.path.read_text()
            self.assertEqual(text.count('DIFFERENCE '), 3)
            summary = json.loads(text.split('SUMMARY ')[1])
            self.assertEqual(summary['matched'], 1)
            self.assertEqual(summary['value_mismatches'], 1)
            self.assertEqual(summary['status'], 'complete')
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_failure_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            report = ReportRun(directory)
            report.finish(RuntimeError('password=secret'))
            text = report.path.read_text()
            self.assertNotIn('secret', text)
            self.assertEqual(json.loads(text.split('SUMMARY ')[1])['status'], 'failed')

    def test_unique_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = ReportRun(directory), ReportRun(directory)
            self.assertNotEqual(a.path, b.path)
            a.finish()
            b.finish()
