from dataclasses import dataclass
from enum import Enum


class Status(str, Enum):
    MATCHED = 'MATCHED'
    MISSING_IN_POSTGRES = 'MISSING_IN_POSTGRES'
    MISSING_IN_ORACLE = 'MISSING_IN_ORACLE'
    VALUE_MISMATCH = 'VALUE_MISMATCH'


@dataclass
class Statistics:
    postgres_total: int = 0
    oracle_total: int = 0
    matched: int = 0
    missing_in_postgres: int = 0
    missing_in_oracle: int = 0
    value_mismatches: int = 0
