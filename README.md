# PostgreSQL–Oracle Table Comparator

Requires Python 3.11+. Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set connection details and schemas in `config/postgres_config.py` and
`config/oracle_config.py`. These credential files are Git-ignored.

## Compare all tables

```powershell
python main.py --postgres-schema public --oracle-schema APIM_INT_APIM
```

Or run `python main.py` to use the schemas saved in the credential files.
No need to change table names manually. Matching table names are found ignoring
case, primary keys are detected, and all columns are compared in batches.

Missing tables, absent/different primary keys, different column sets and failed
tables are reported explicitly. A run with these issues is marked incomplete.
Only accessible base tables are discovered; views and synonyms are excluded.
Schema mode ignores manual table/key/column settings; it uses only batch_size.

Each table gets a timestamped log containing every missing key, each changed
column with both values, progress and final totals. The overall log lists table
outcomes and log paths. All output is in `logs/`; no CSV reports are generated.
Keys must identify equivalent records in both databases. Compare stable data
for reliable results; different tables are read at different times.

## Other commands

```powershell
python main.py --metadata-only   # Discover tables and validate without reading rows
python main.py --single-table    # Use manual config/comparison_config.py settings
python main.py --batch-size 5000 # Adjust fetch size
python main.py --demo            # Offline example
python -m unittest discover -q   # Tests
```

Large-value tables use the configured cap (currently 500 rows per fetch); ordinary tables
keep the configured batch size. Change `large_value_batch_size` in comparison
configuration or pass `--large-value-batch-size 50`. A smaller `--batch-size` is
always respected. This limits rows, not bytes: one very large value can still
use substantial memory. Fetch timings appear in the logs, and fetched row counts
appear in the console. Detailed differences, progress, errors and totals are written to the logs. Restart an existing run to use these changes.

Schema runs use two concurrent workers and reuse each worker's database
connections. Every table starts a fresh read-only transaction; failed sessions
are discarded. No connection is shared between workers. Concurrency increases
memory and database load; use `--workers 1` for sequential execution or up to
`--workers 4` if your servers can handle it. A cancellation waits for in-flight
database calls before stopping; already completed table reports remain valid.

For tuning, compare total duration on stable data with:

```powershell
python main.py --workers 2 --large-value-batch-size 100
python main.py --workers 2 --large-value-batch-size 500
python main.py --workers 2 --large-value-batch-size 1000
```

These commands each perform a full comparison. Larger batches are not always
faster. The default 500 is a starting point, not a measured optimum. Connection
reuse and concurrency preserve the existing value comparison rules; snapshots
are per table, not coordinated across both databases or the whole schema.
