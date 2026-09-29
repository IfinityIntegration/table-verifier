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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata-only', action='store_true')
    parser.add_argument('--batch-size', type=int)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
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
            if args.batch_size is not None:
                settings['batch_size'] = args.batch_size
            config = ComparisonConfig(**settings)
            if report:
                report.configure(postgres_table=POSTGRES_CONFIG['schema'] + '.' + config.postgres_table,
                                 oracle_table=ORACLE_CONFIG['schema'] + '.' + config.oracle_table,
                                 comparison_key=list(config.keys), batch_size=config.batch_size)
            with PostgresClient(POSTGRES_CONFIG) as pg, OracleClient(ORACLE_CONFIG) as oracle:
                pg.test_connection()
                oracle.test_connection()
                plan = build_plan(config, pg.get_columns(config.postgres_table), oracle.get_columns(config.oracle_table))
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
                    with closing(pg.fetch_batches(config.postgres_table, plan.postgres_select, config.batch_size, plan.postgres_select[:count])) as left, closing(oracle.fetch_batches(config.oracle_table, plan.oracle_select, config.batch_size, plan.oracle_select[:count])) as right:
                        run_comparison(left, right, plan.postgres_select, count, report)
        if report:
            report.finish()
        return 0
    except (Exception, KeyboardInterrupt) as error:
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
