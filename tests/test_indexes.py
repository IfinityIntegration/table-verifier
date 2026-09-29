import unittest
from comparator.index_support import supporting_indexes


class IndexTests(unittest.TestCase):
    def test_leading_keys(self):
        rows = [('good', 'tenant', 1), ('good', 'id', 2), ('good', 'extra', 3),
                ('wrong', 'id', 1), ('wrong', 'tenant', 2), ('gap', 'tenant', 2)]
        self.assertEqual(supporting_indexes(rows, ['tenant', 'id']), ['good'])
        self.assertEqual(supporting_indexes(rows, ['tenant']), ['good'])
        self.assertEqual(supporting_indexes([], ['id']), [])
