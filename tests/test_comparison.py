import unittest
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from comparator.table_comparator import compare_streams
from comparator.value_normalizer import normalize
from utils.errors import ConfigurationError


class ComparisonTests(unittest.TestCase):
    def test_all_statuses_and_multiple_columns(self):
        events = []
        result = compare_streams([[(1, 'a', 1)], [(2, 'b', 2), (4, 'd', 4)]],
                                 [[(1, 'a', Decimal('1.0')), (2, 'B', 3)], [(3, 'c', 3)]],
                                 ['id', 'name', 'value'], 1, events.append)
        self.assertEqual((result.postgres_total, result.oracle_total), (3, 3))
        self.assertEqual((result.matched, result.value_mismatches, result.missing_in_postgres, result.missing_in_oracle), (1, 1, 1, 1))
        self.assertEqual(len(events[1]['differences']), 2)
        self.assertEqual(events[1]['primary_key'], [2])
        self.assertEqual(events[1]['differences'][0]['column'], 'name')

    def test_empty_and_exhausted(self):
        self.assertEqual(compare_streams([], [], ['id'], 1).matched, 0)
        result = compare_streams([], [[(1,), (2,)]], ['id'], 1)
        self.assertEqual(result.missing_in_postgres, 2)
        result = compare_streams([[(1,), (2,)]], [], ['id'], 1)
        self.assertEqual(result.missing_in_oracle, 2)

    def test_composite(self):
        result = compare_streams([[(1, 1), (1, 2)]], [[(1, 2), (2, 1)]], ['tenant', 'id'], 2)
        self.assertEqual((result.matched, result.missing_in_postgres, result.missing_in_oracle), (1, 1, 1))

    def test_invalid_keys_across_batches(self):
        for batches in ([[(1,)], [(1,)]], [[(2,)], [(1,)]], [[(None,)]], [[(1,)], [('2',)]]):
            with self.subTest(batches=batches), self.assertRaises(ConfigurationError):
                compare_streams(batches, [], ['id'], 1)
        with self.assertRaises(ConfigurationError):
            compare_streams([[(1,)]], [[('1',)]], ['id'], 1)

    def test_normalization(self):
        self.assertEqual(normalize(True), normalize(Decimal('1')))
        self.assertEqual(normalize(date(2026, 1, 1)), normalize(datetime(2026, 1, 1)))
        self.assertEqual(normalize(datetime(2026, 1, 1, tzinfo=timezone.utc)), normalize(datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1)))))
        self.assertNotEqual(normalize(None), normalize(''))
        self.assertNotEqual(normalize('a ', key=True), normalize('a', key=True))
        self.assertEqual(normalize('a '), normalize('a'))
        self.assertEqual(normalize(Decimal('123456789012345678901234567890.123')), ('number', Decimal('123456789012345678901234567890.123')))
        for value in (float('nan'), float('inf'), object()):
            with self.assertRaises(ConfigurationError):
                normalize(value)

    def test_lazy_input(self):
        progress = [0]
        def source():
            for i in range(10000):
                progress[0] += 1
                yield [(i,)]
        def emit(event):
            # Only one lookahead row is held from each stream.
            self.assertLessEqual(progress[0], event['primary_key'][0] + 1)
        result = compare_streams(source(), ([(i,)] for i in range(10000)), ['id'], 1, emit)
        self.assertEqual(result.matched, 10000)

    def test_lob(self):
        class Lob:
            def read(self):
                return 'hello'
        self.assertEqual(compare_streams([[(1, 'hello')]], [[(1, Lob())]], ['id', 'text'], 1).matched, 1)


if __name__ == '__main__':
    unittest.main()
