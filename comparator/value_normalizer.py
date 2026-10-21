"""Explicit normalization; unsupported types fail rather than compare as strings."""
from datetime import date, datetime, timezone
from decimal import Decimal
from utils.errors import ConfigurationError


def materialize(value):
    return value.read() if hasattr(value, 'read') else value


def normalize(value, *, key=False):
    value = materialize(value)
    if value is None:
        return ('null',)
    if isinstance(value, (bool, int, float, Decimal)):
        number = Decimal(str(value)) if not isinstance(value, bool) else Decimal(int(value))
        if not number.is_finite():
            raise ConfigurationError('Non-finite numeric values are not supported')
        return ('number', number)
    if isinstance(value, datetime):
        # Compare data values at whole-second precision; identities stay exact.
        if not key:
            value = value.replace(microsecond=0)
        if value.utcoffset() is not None:
            return ('aware_datetime', value.astimezone(timezone.utc))
        return ('datetime', value)
    if isinstance(value, date):
        return ('datetime', datetime.combine(value, datetime.min.time()))
    if isinstance(value, str):
        # Keys retain spaces to avoid merging distinct identities.
        return ('text', value if key else value.rstrip(' '))
    if isinstance(value, (bytes, bytearray, memoryview)):
        return ('binary', bytes(value))
    raise ConfigurationError(f'Unsupported value type: {type(value).__name__}')


def report_value(value):
    value = materialize(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {'type': 'binary', 'hex': bytes(value).hex()}
    if isinstance(value, (Decimal, date, datetime)):
        return {'type': type(value).__name__, 'value': str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ConfigurationError(f'Unsupported report value type: {type(value).__name__}')


def values_equal(left, right, *, key=False):
    """Text/BLOB equivalence requires exact UTF-8 bytes; no lossy decoding."""
    if not key:
        # Some Oracle flag columns expose booleans as character digits.
        if isinstance(left, bool) and isinstance(right, str) and right in ('0', '1'):
            return int(left) == int(right)
        if isinstance(right, bool) and isinstance(left, str) and left in ('0', '1'):
            return int(right) == int(left)
        # Oracle stores empty character strings as NULL.
        if (left is None and isinstance(right, str) and right == '') or (
                right is None and isinstance(left, str) and left == ''):
            return True
        binary = (bytes, bytearray, memoryview)
        if isinstance(left, str) and isinstance(right, binary):
            return left.encode('utf-8') == bytes(right)
        if isinstance(right, str) and isinstance(left, binary):
            return right.encode('utf-8') == bytes(left)
        # Full-row checking preserves whitespace differences in textual values.
        if isinstance(left, str) and isinstance(right, str):
            return left == right
    return normalize(left, key=key) == normalize(right, key=key)
