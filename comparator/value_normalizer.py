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
