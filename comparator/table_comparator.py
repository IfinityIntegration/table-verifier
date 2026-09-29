"""Linear merge of sorted unique-key streams; no accumulation of results."""
from comparator.models import Statistics, Status
from comparator.value_normalizer import materialize, normalize, report_value
from utils.errors import ConfigurationError


def checked_rows(batches, columns, key_count, side):
    previous = None
    for batch in batches:
        for raw in batch:
            if len(raw) != len(columns):
                raise ConfigurationError(f'{side}: unexpected row width')
            row = tuple(materialize(v) for v in raw)
            key = tuple(normalize(v, key=True) for v in row[:key_count])
            if any(v[0] == 'null' for v in key):
                raise ConfigurationError(f'{side}: NULL comparison key')
            if previous is not None:
                if tuple(v[0] for v in previous) != tuple(v[0] for v in key):
                    raise ConfigurationError(f'{side}: inconsistent key types')
                if key <= previous:
                    raise ConfigurationError(f'{side}: duplicate key or incompatible database sort order')
            previous = key
            yield key, row


def compare_streams(postgres_batches, oracle_batches, columns, key_count, emit=lambda event: None):
    """Keys must be the first key_count columns, in the same order on both sides."""
    if not 1 <= key_count <= len(columns):
        raise ConfigurationError('Invalid key column count')
    stats = Statistics()
    pg = iter(checked_rows(postgres_batches, columns, key_count, 'PostgreSQL'))
    ora = iter(checked_rows(oracle_batches, columns, key_count, 'Oracle'))
    left, right = next(pg, None), next(ora, None)
    while left is not None or right is not None:
        if left is not None and right is not None:
            if tuple(v[0] for v in left[0]) != tuple(v[0] for v in right[0]):
                raise ConfigurationError('Comparison key types differ between databases')
        if right is None or (left is not None and left[0] < right[0]):
            status, row = Status.MISSING_IN_ORACLE, left[1]
            stats.postgres_total += 1
            stats.missing_in_oracle += 1
            emit({'status': status.value, 'primary_key': [report_value(v) for v in row[:key_count]]})
            left = next(pg, None)
        elif left is None or right[0] < left[0]:
            status, row = Status.MISSING_IN_POSTGRES, right[1]
            stats.oracle_total += 1
            stats.missing_in_postgres += 1
            emit({'status': status.value, 'primary_key': [report_value(v) for v in row[:key_count]]})
            right = next(ora, None)
        else:
            stats.postgres_total += 1
            stats.oracle_total += 1
            differences = [{'column': columns[i], 'postgres_value': report_value(a), 'oracle_value': report_value(b)}
                           for i, (a, b) in enumerate(zip(left[1], right[1]))
                           if normalize(a, key=i < key_count) != normalize(b, key=i < key_count)]
            status = Status.VALUE_MISMATCH if differences else Status.MATCHED
            if differences:
                stats.value_mismatches += 1
            else:
                stats.matched += 1
            emit({'status': status.value, 'primary_key': [report_value(v) for v in left[1][:key_count]],
                  'differences': differences})
            left, right = next(pg, None), next(ora, None)
    return stats
