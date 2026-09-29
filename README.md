# PostgreSQL–Oracle Table Comparator

Checks which rows are missing from either database using a shared unique key.
Requires Python 3.11+.

## Setup

```powershell
python -m pip install -r requirements.txt
```

Set your connection details in:
- `config/postgres_config.py`
- `config/oracle_config.py`

If these files are missing, copy the corresponding `.example.py` files first.
Credential files are ignored by Git.

## Configure

Edit `config/comparison_config.py` to set table names, comparison keys,
columns and batch size.

Currently, only `operation_policy_mapping_id` is compared. Other column values
are ignored. Keys must identify the same records in both databases.

## Run

```powershell
python main.py
```

Results appear in the console. Every difference and the final totals are saved
in one timestamped file under `logs/`. Databases are read only.

Optional commands:

```powershell
python main.py --demo             # Test without databases
python main.py --metadata-only    # Check table configuration
python -m unittest discover -q    # Run tests
```
