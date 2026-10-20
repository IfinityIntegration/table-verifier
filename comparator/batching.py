"""Conservative type-based fetch sizing, independent of comparison semantics."""
from utils.errors import ConfigurationError

LARGE_TYPES = {'blob', 'clob', 'nclob', 'bfile', 'long', 'long raw', 'bytea', 'text', 'json', 'jsonb', 'xml', 'xmltype'}


def validate_large_batch(size):
    if type(size) is not int or not 1 <= size <= 100000:
        raise ConfigurationError('large_value_batch_size must be between 1 and 100000')


def choose_batch_size(requested, pg_columns, ora_columns, selected, large_value_batch_size=100):
    validate_large_batch(large_value_batch_size)
    selected = {name.casefold() for name in selected}
    large = sorted({c.name.casefold() for c in [*pg_columns, *ora_columns]
                    if c.name.casefold() in selected and c.data_type.lower() in LARGE_TYPES})
    return (min(requested, large_value_batch_size) if large else requested), large
