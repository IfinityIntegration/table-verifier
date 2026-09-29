"""Conservative advisory check; the database optimizer chooses the actual plan."""
from collections import defaultdict


def supporting_indexes(rows, keys):
    indexes = defaultdict(list)
    for name, column, position in rows:
        indexes[name].append((int(position), column))
    return [name for name, entries in indexes.items()
            if sorted(entries)[:len(keys)] == list(enumerate(keys, 1))]


def describe_indexes(client, table, keys):
    rows = client._query(client.index_sql, client._params(table))
    names = supporting_indexes(rows, keys)
    if names:
        return f'{client.side} compatible ascending B-tree indexes: {names} (optimizer decides usage)'
    return (f'{client.side}: no eligible ascending B-tree index found for {list(keys)}. '
            'Comparison remains exact; database sorting may be required. Ask your DBA to review a key index.')
