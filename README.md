# PostgreSQL–Oracle table comparator

Python 3.11+. Credentials remain in separate Git-ignored files:
`config/postgres_config.py` and `config/oracle_config.py`. Example files are
provided for fresh installations; do not overwrite populated local files.

```powershell
python -m pip install -r requirements.txt
python main.py --metadata-only
python main.py --demo
python main.py
python -m unittest discover -v
```

`--demo` is entirely offline. Normal execution compares configured tables using
read-only SELECTs. Exit status 0 means the run completed (even with differences);
1 means failure. Inspect summary statistics for equality.

## Configuration

`config/comparison_config.py` specifies table names, keys (single/composite),
columns, ignore_columns, and batch_size. Schemas are in database configurations.
Use exact schema/table spelling. Columns match case-insensitively; ambiguous
case variants are rejected. Empty columns means all common non-ignored columns.
Keys are always selected first. Missing keys, unknown selections and selecting
and ignoring the same column are rejected. Default batch size is 10000.

## Algorithm and memory

Both SELECTs include ORDER BY on all key components. PostgreSQL reads through a
named server cursor; Oracle uses fetchmany and arraysize. The comparator holds
one current row per stream, compares keys, advances the smaller key, or compares
values and advances both when keys match. Processing is O(n + m) for a fixed
column count. Memory is O(batch_size * row size), plus the current row and its
mismatches, not total table size. Large LOB values are materialized one row at a
time and can dominate memory. Database sorting may require O(n log n) work and
temporary disk; an appropriate key index can help.

Sorted order must agree with Python's normalized key order. Every stream is
checked for strict increase; NULL keys, duplicates (including across batches),
key-type changes and incompatible collations fail the run. Text key collation
can differ across databases; this release detects incompatible stream order
rather than silently reporting wrong results. It does not force a database
collation or normalize key whitespace. Date/time-aware and naive keys cannot
be mixed. Views and synonyms are outside the table-only metadata scope.

## Normalization

- NULL is distinct from empty text; Oracle empty strings normally arrive as NULL.
- Non-key strings ignore trailing ASCII spaces, preserving case, leading spaces,
  tabs and newlines. Keys preserve all whitespace.
- Numeric values use Decimal; Oracle NUMBER is fetched through a Decimal output
  handler to preserve precision. Float comparison uses its decimal string form,
  with no tolerance. Boolean true/false equals numeric 1/0, not text labels.
- Dates equal naive timestamps at midnight. Timezone-aware timestamps are
  converted to UTC; naive timestamps remain distinct from aware timestamps.
- Oracle LOBs are read while connected; binary values compare exactly.
- Unsupported values and non-finite numbers fail explicitly. No string coercion
  of arbitrary database types is attempted.

## Reports and logs

Each execution writes one timestamped `logs/comparison_<UTC timestamp>_<id>.log`.
It contains connection status, configuration (without credentials), progress,
every missing key and every changed column with both values, and a final SUMMARY
entry with counts, timing and completion status. Matches are counted, not listed.
Differences are JSON-encoded on individual log lines to preserve types and escape
embedded newlines. Output is written incrementally, not collected in memory.

No CSV or JSON report files are generated. Logs do not rotate during a run, so
all differences are retained. Archive or remove old logs according to your
retention needs. Logs contain table values and are Git-ignored. `--debug` enables
batch-level diagnostics. A failed run has a failed SUMMARY with partial counts;
a log without a SUMMARY is incomplete. Hierarchical mode is not implemented.

## Modules

- `db/`: connection lifecycle, bound metadata queries, quoted SELECT identifiers,
  ordered batch readers; caller must consume generators inside client contexts.
- `comparator/metadata.py`: configuration and shared-column selection plans.
- `comparator/value_normalizer.py`: normalization and report serialization.
- `comparator/models.py`: statuses and statistics.
- `comparator/table_comparator.py`: independently testable streaming merge.
- `comparator/reporting.py`: per-run log, differences and completion reporting.
- `main.py`: metadata display and comparison orchestration.
- `tests/`: offline normalization, merge, metadata, SQL safety and lifecycle tests.

For direct batch-reader use, wrap generators in contextlib.closing when stopping
early. Metadata queries use fetchall only for column descriptions, never table
rows. Source reads do not constitute a synchronized cross-database snapshot;
compare quiescent tables or coordinate snapshots externally for reliable
migration verification while applications are writing.

Driver references:
https://www.psycopg.org/psycopg3/docs/advanced/cursors.html
https://python-oracledb.readthedocs.io/en/stable/api_manual/cursor.html

## Indexed streaming merge

The existing exact merge now checks the database catalogs for valid ascending
B-tree indexes with the comparison keys as their leading columns, in order.
These checks are conservative: partial/expression/descending indexes and Oracle
partitioned indexes not reported VALID are not recommended by this check.
An advisory is printed and logged. No indexes or other database objects are
created. Index availability does not prove index usage: the optimizer may prefer
a sequential scan and sort, especially for small tables or full-table reads.
Ask a DBA to review actual execution plans before adding an index.

Tune network batch size without changing configuration:

```powershell
python main.py --batch-size 5000
python main.py --batch-size 10000
python main.py --batch-size 25000
```

Each completed summary records duration in seconds, including setup, metadata,
index checks, fetching, normalization and report writing. Benchmark on representative stable data; caches and concurrent
load affect timing. Indexes can reduce sorting costs, while batching reduces
network round trips. Neither changes comparison equality or the linear merge.
