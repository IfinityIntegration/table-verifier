"""Edit table names here; schemas come from the separate database configs."""
COMPARISON_CONFIG = {
    "postgres_table": "um_user",
    "oracle_table": "UM_USER",
    "keys": ["um_id"],
    # Compare all common columns; same ID with changed values is a mismatch.
    "columns": [],
    "ignore_columns": [],
    "batch_size": 10000,
    "workers": 2,  # Each worker owns one connection to each database.
    "large_value_batch_size": 500,  # Automatic cap for selected LOB/text/binary columns.
}
