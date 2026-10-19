"""Application entry point; comparison algorithm stays in table_comparator."""
import argparse
from contextlib import closing
import logging
from pathlib import Path
from comparator.metadata import ComparisonConfig, build_plan
from comparator.reporting import ReportRun, run_comparison
from comparator.index_support import describe_indexes
from db.postgres_client import PostgresClient
from db.oracle_client import OracleClient
from utils.errors import ConfigurationError
from comparator.batching import choose_batch_size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata-only', action='store_true')
    parser.add_argument('--batch-size', type=int)
    parser.add_argument('--large-value-batch-size', type=int, help='Override configured batch cap for LOB/text/binary columns')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--workers', type=int, help='Concurrent table workers, 1 to 4 (default 2)')
    parser.add_argument('--single-table', action='store_true', help='Use the manual table/key configuration')
    parser.add_argument('--postgres-schema', help='Override the PostgreSQL schema')
    parser.add_argument('--oracle-schema', help='Override the Oracle schema')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if not args.demo and not args.single_table:
        from config.postgres_config import POSTGRES_CONFIG
        from config.oracle_config import ORACLE_CONFIG
        from config.comparison_config import COMPARISON_CONFIG
        from comparator.schema_comparator import compare_schema
        pg_config, ora_config = dict(POSTGRES_CONFIG), dict(ORACLE_CONFIG)
        if args.postgres_schema:
            pg_config['schema'] = args.postgres_schema
        if args.oracle_schema:
            ora_config['schema'] = args.oracle_schema
        return compare_schema(root, pg_config, ora_config,
                              args.batch_size if args.batch_size is not None else COMPARISON_CONFIG.get('batch_size', 10000),
                              args.metadata_only, args.debug,
                              args.large_value_batch_size if args.large_value_batch_size is not None else COMPARISON_CONFIG.get('large_value_batch_size', 100),
                              args.workers if args.workers is not None else COMPARISON_CONFIG.get('workers', 2))
    (root / 'logs').mkdir(exist_ok=True)
    report = ReportRun(root / 'logs')
    log_path = report.path
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        handlers=[report.handler], force=True)
    for name in ('psycopg', 'oracledb'):
        logging.getLogger(name).disabled = True
    try:
        if args.demo:
            report.configure(postgres_table='demo.postgres', oracle_table='demo.oracle',
                             comparison_key=['id'], columns=['id', 'name'], batch_size=3)
            run_comparison([[(1, 'Alice'), (2, 'Bob'), (4, 'Dana')]],
                           [[(1, 'Alice '), (2, 'Bobby'), (3, 'Carol')]], ['id', 'name'], 1, report)
        else:
            from config.postgres_config import POSTGRES_CONFIG
            from config.oracle_config import ORACLE_CONFIG
            from config.comparison_config import COMPARISON_CONFIG
            settings = dict(COMPARISON_CONFIG)
            settings.pop('workers', None)
            if args.batch_size is not None:
                settings['batch_size'] = args.batch_size
            if args.large_value_batch_size is not None:
                settings['large_value_batch_size'] = args.large_value_batch_size
            config = ComparisonConfig(**settings)
            if report:
                report.configure(postgres_table=POSTGRES_CONFIG['schema'] + '.' + config.postgres_table,
                                 oracle_table=ORACLE_CONFIG['schema'] + '.' + config.oracle_table,
                                 comparison_key=list(config.keys), batch_size=config.batch_size)
            with PostgresClient(POSTGRES_CONFIG) as pg, OracleClient(ORACLE_CONFIG) as oracle:
                pg.test_connection()
                oracle.test_connection()
                pg_columns = pg.get_columns(config.postgres_table)
                ora_columns = oracle.get_columns(config.oracle_table)
                plan = build_plan(config, pg_columns, ora_columns)
                effective_batch, large_columns = choose_batch_size(config.batch_size, pg_columns, ora_columns, plan.postgres_select, config.large_value_batch_size)
                report.configure(requested_batch_size=config.batch_size, effective_batch_size=effective_batch, large_value_columns=large_columns)
                print(f'Fetch batch: {effective_batch:,}; large-value columns: {large_columns}', flush=True)
                if plan.postgres_only or plan.oracle_only:
                    logging.warning('Schema differences: PostgreSQL-only=%s Oracle-only=%s', plan.postgres_only, plan.oracle_only)
                    print(f'Columns only in PostgreSQL: {list(plan.postgres_only)}; only in Oracle: {list(plan.oracle_only)}')
                logging.info('Columns compared=%s', plan.postgres_select)
                if report:
                    report.configure(columns=list(plan.postgres_select))
                for client, table, selected in ((pg, config.postgres_table, plan.postgres_select),
                                                (oracle, config.oracle_table, plan.oracle_select)):
                    advisory = describe_indexes(client, table, selected[:len(config.keys)])
                    logging.log(logging.WARNING if 'no eligible' in advisory else logging.INFO, advisory)
                if args.metadata_only:
                    print(f'Common columns: {list(plan.common)}\nPostgreSQL-only: {list(plan.postgres_only)}\nOracle-only: {list(plan.oracle_only)}')
                else:
                    count = len(config.keys)
                    with closing(pg.fetch_batches(config.postgres_table, plan.postgres_select, effective_batch, plan.postgres_select[:count])) as left, closing(oracle.fetch_batches(config.oracle_table, plan.oracle_select, effective_batch, plan.oracle_select[:count])) as right:
                        run_comparison(left, right, plan.postgres_select, count, report)
        if report:
            report.finish()
        return 0
    except (Exception, KeyboardInterrupt) as error:
        if isinstance(error, ConfigurationError):
            # Application validation messages contain table/column details, not driver credentials.
            logging.error('Configuration error: %s', error)
            print(f'Configuration error: {error}')
        else:
            logging.error('Execution failed exception_type=%s; exception text suppressed to protect credentials', type(error).__name__)
            print(f'Execution failed ({type(error).__name__}). Check configuration, database access and the application log.')
        if report:
            try:
                report.finish(error)
            except Exception as reporting_error:
                logging.error('Could not finalize report exception_type=%s', type(reporting_error).__name__)
                print('Log finalization failed; a run without a SUMMARY entry is incomplete.')
        return 1
    finally:
        logging.getLogger().removeHandler(report.handler)
        report.handler.close()


if __name__ == '__main__':
    raise SystemExit(main())
