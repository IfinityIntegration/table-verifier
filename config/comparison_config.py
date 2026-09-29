"""Edit table names here; schemas come from the separate database configs."""
COMPARISON_CONFIG = {
    "postgres_table": "am_api_operation_policy_mapping",
    "oracle_table": "AM_API_OPERATION_POLICY_MAPPING",
    "keys": ["operation_policy_mapping_id"],
    # Row-existence check only: do not fetch or compare non-key values.
    "columns": ["operation_policy_mapping_id"],
    "ignore_columns": [],
    "batch_size": 10000,
}
