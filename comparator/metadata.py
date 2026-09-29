from dataclasses import dataclass
from utils.errors import ConfigurationError


def identifier(name):
    if not isinstance(name, str) or not name or '\x00' in name:
        raise ConfigurationError('Identifiers must be nonempty strings without NUL characters')
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    nullable: bool
    position: int


@dataclass(frozen=True)
class ComparisonConfig:
    postgres_table: str
    oracle_table: str
    keys: tuple[str, ...]
    columns: tuple[str, ...] = ()
    ignore_columns: tuple[str, ...] = ()
    batch_size: int = 10000

    def __post_init__(self):
        identifier(self.postgres_table)
        identifier(self.oracle_table)
        for field in ('keys', 'columns', 'ignore_columns'):
            values = getattr(self, field)
            if not isinstance(values, (list, tuple)):
                raise ConfigurationError(f'{field} must be a list of names')
            for value in values:
                identifier(value)
            if len({v.casefold() for v in values}) != len(values):
                raise ConfigurationError(f'Duplicate names in {field}')
            object.__setattr__(self, field, tuple(values))
        if not self.keys:
            raise ConfigurationError('At least one comparison key is required')
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 100000:
            raise ConfigurationError('batch_size must be between 1 and 100000')


def column_index(columns):
    result = {}
    for column in columns:
        key = column.name.casefold()
        if key in result:
            raise ConfigurationError('Ambiguous case-insensitive column names')
        result[key] = column.name
    return result


@dataclass(frozen=True)
class MetadataPlan:
    common: tuple[str, ...]
    postgres_only: tuple[str, ...]
    oracle_only: tuple[str, ...]
    postgres_select: tuple[str, ...]
    oracle_select: tuple[str, ...]


def build_plan(config, postgres_columns, oracle_columns):
    pg, ora = column_index(postgres_columns), column_index(oracle_columns)
    common = [n for n in pg if n in ora]
    keys = [n.casefold() for n in config.keys]
    ignored = {n.casefold() for n in config.ignore_columns}
    requested = [n.casefold() for n in config.columns]
    if any(k not in common for k in keys):
        raise ConfigurationError('Every comparison key must exist in both tables')
    if ignored.intersection(keys):
        raise ConfigurationError('Comparison keys cannot be ignored')
    if ignored - (pg.keys() | ora.keys()):
        raise ConfigurationError('Unknown ignored column')
    if any(n not in common for n in requested):
        raise ConfigurationError('Requested columns must exist in both tables')
    if ignored.intersection(requested):
        raise ConfigurationError('A column cannot be selected and ignored')
    selected = keys + [n for n in (requested or common) if n not in ignored and n not in keys]
    return MetadataPlan(tuple(pg[n] for n in common),
                        tuple(pg[n] for n in pg if n not in ora),
                        tuple(ora[n] for n in ora if n not in pg),
                        tuple(pg[n] for n in selected), tuple(ora[n] for n in selected))
