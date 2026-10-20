import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from decimal import Decimal
from db.oracle_client import OracleClient


class OracleLobTests(unittest.TestCase):
    def test_batch_lob_types_and_decimal_precision(self):
        driver = MagicMock()
        for name in ('BLOB', 'CLOB', 'LONG_RAW', 'LONG', 'NUMBER', 'VARCHAR'):
            setattr(driver, 'DB_TYPE_' + name, name)
        config = dict(host='test', port=1521, service_name='test', username='test', password='test', schema='TEST')
        with patch.dict(sys.modules, {'oracledb': driver}):
            connection = OracleClient(config)._connect()
        handler = connection.outputtypehandler
        cursor = MagicMock()
        cursor.arraysize = 100
        handler(cursor, SimpleNamespace(type_code='BLOB'))
        cursor.var.assert_called_with('LONG_RAW', arraysize=100)
        handler(cursor, SimpleNamespace(type_code='CLOB'))
        cursor.var.assert_called_with('LONG', arraysize=100)
        handler(cursor, SimpleNamespace(type_code='NUMBER'))
        cursor.var.assert_called_with('VARCHAR', arraysize=100, outconverter=Decimal)
        self.assertIsNone(handler(cursor, SimpleNamespace(type_code='OTHER')))
