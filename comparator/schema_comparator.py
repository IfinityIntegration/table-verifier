"""Bounded concurrent schema orchestration around the existing streaming comparator."""
import logging
import csv
import json
import threading
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from dataclasses import asdict
from db.schema_metadata import list_tables, primary_key, match_tables, shared_key
from db.postgres_client import PostgresClient
from db.oracle_client import OracleClient
from comparator.metadata import ComparisonConfig, build_plan
from comparator.reporting import ReportRun, run_comparison
from utils.errors import ConfigurationError
from comparator.batching import choose_batch_size, validate_large_batch


def compare_schema(root, pg_config, ora_config, batch_size=10000, metadata_only=False, debug=False, large_value_batch_size=100, workers=2):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ConfigurationError('workers must be between 1 and 4')
    validate_large_batch(large_value_batch_size)
    # Validate batch size before connecting, even for an empty schema.
    ComparisonConfig('validation', 'validation', ['id'], batch_size=batch_size)
    master = ReportRun(root / 'logs')
    report_directory = root / 'reports'
    report_directory.mkdir(exist_ok=True)
    issues_path = report_directory / f'schema_issues_{master.execution_id}.csv'
    issues_stream = issues_path.open('x', encoding='utf-8-sig', newline='')
    issues_writer = csv.writer(issues_stream)
    issues_writer.writerow(['postgres_table', 'oracle_table', 'status', 'primary_key', 'column', 'postgres_value', 'oracle_value', 'reason'])
    issues_lock = threading.Lock()

    def write_issue(pg_table='', ora_table='', status='', key='', column='', pg_value='', ora_value='', reason=''):
        with issues_lock:
            issues_writer.writerow([pg_table, ora_table, status, key, column, pg_value, ora_value, reason])
            issues_stream.flush()
    logger = logging.getLogger()
    old_handlers, old_level = logger.handlers[:], logger.level
    logger.handlers = [master.handler]
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    for name in ('psycopg', 'oracledb'):
        logging.getLogger(name).disabled = True
    results = []
    completed_stats = {name: 0 for name in asdict(master.stats)}
    try:
        master.configure(comparison_scope='schema', postgres_schema=pg_config['schema'], oracle_schema=ora_config['schema'], batch_size=batch_size, metadata_only=metadata_only)
        with PostgresClient(pg_config) as pg, OracleClient(ora_config) as ora:
            pg.test_connection()
            ora.test_connection()
            pairs, pg_only, ora_only = match_tables(list_tables(pg), list_tables(ora))
        for name in pg_only:
            results.append({'table': name, 'status': 'MISSING_TABLE_IN_ORACLE'})
            write_issue(pg_table=name, status='MISSING_TABLE_IN_ORACLE')
        for name in ora_only:
            results.append({'table': name, 'status': 'MISSING_TABLE_IN_POSTGRES'})
            write_issue(ora_table=name, status='MISSING_TABLE_IN_POSTGRES')
        for result in results:
            logging.warning('%s', result)
            print(result['status'] + ': ' + result['table'])
        if not pairs:
            raise ConfigurationError('No common accessible tables found in the configured schemas')
        jobs = Queue()
        for job in enumerate(pairs, 1):
            jobs.put(job)
        stop = threading.Event()
        result_lock = threading.Lock()
        master.configure(workers=workers, large_value_batch_size=large_value_batch_size)
        def worker():
            pg, ora = PostgresClient(pg_config), OracleClient(ora_config)
            try:
                while not stop.is_set():
                    try:
                        index, (pg_table, ora_table) = jobs.get_nowait()
                    except Empty:
                        return
                    process_table(index, pg_table, ora_table, pg, ora)
            finally:
                for client in (pg, ora):
                    try:
                        client.close()
                    except Exception:
                        logging.warning('Worker connection cleanup failed')

        def process_table(index, pg_table, ora_table, pg, ora):
            print(f'[{index}/{len(pairs)}] {pg_table} / {ora_table}', flush=True)
            report = ReportRun(root / 'logs')
            # Root database logs must go only to this worker's table log.
            report.handler.addFilter(ThreadFilter(threading.get_ident()))
            logger.addHandler(report.handler)
            outcome = {'postgres_table': pg_table, 'oracle_table': ora_table, 'log': str(report.path)}
            try:
                # Roll back and restart a read-only transaction before reusing sessions.
                pg.begin_table()
                ora.begin_table()
                report.configure(postgres_table=pg_config['schema']+'.'+pg_table, oracle_table=ora_config['schema']+'.'+ora_table, batch_size=batch_size)
                keys = shared_key(primary_key(pg, pg_table), primary_key(ora, ora_table))
                config = ComparisonConfig(pg_table, ora_table, keys, batch_size=batch_size)
                pg_columns, ora_columns = pg.get_columns(pg_table), ora.get_columns(ora_table)
                plan = build_plan(config, pg_columns, ora_columns)
                effective_batch, large_columns = choose_batch_size(batch_size, pg_columns, ora_columns, plan.postgres_select, large_value_batch_size)
                report.configure(requested_batch_size=batch_size, effective_batch_size=effective_batch, large_value_columns=large_columns)
                print(f'  Fetch batch: {effective_batch:,}; large-value columns: {large_columns}', flush=True)
                report.configure(comparison_key=keys, columns=list(plan.postgres_select))
                if plan.postgres_only or plan.oracle_only:
                    raise ConfigurationError(f'Column sets differ: PostgreSQL-only={list(plan.postgres_only)}; Oracle-only={list(plan.oracle_only)}')
                if not metadata_only:
                    n = len(keys)
                    with closing(pg.fetch_batches(pg_table, plan.postgres_select, effective_batch, plan.postgres_select[:n])) as left, closing(ora.fetch_batches(ora_table, plan.oracle_select, effective_batch, plan.oracle_select[:n])) as right:
                        class IssueReport:
                            def emit(self, event):
                                report.emit(event)
                                if event['status'] == 'MATCHED':
                                    return
                                key = json.dumps(event['primary_key'], ensure_ascii=True)
                                for diff in event.get('differences') or [{}]:
                                    write_issue(pg_table, ora_table, event['status'], key, diff.get('column', ''),
                                                json.dumps(diff.get('postgres_value'), ensure_ascii=True),
                                                json.dumps(diff.get('oracle_value'), ensure_ascii=True))
                        run_comparison(cancellable(left, stop), cancellable(right, stop), plan.postgres_select, n, IssueReport())
                outcome['status'] = 'METADATA_VALIDATED' if metadata_only else 'COMPLETE'
                report.finish()
                with result_lock:
                    for name, value in asdict(report.stats).items():
                        completed_stats[name] += value
            except Exception as error:
                for client in (pg, ora):
                    try:
                        client.close()
                    except Exception:
                        pass
                outcome['status'] = 'NOT_COMPARED' if isinstance(error, ConfigurationError) and report.events == 0 else 'FAILED'
                outcome['reason'] = str(error) if isinstance(error, ConfigurationError) else type(error).__name__
                write_issue(pg_table, ora_table, outcome['status'], reason=outcome['reason'])
                print(f"{outcome['status']}: {outcome['reason']}", flush=True)
                report.logger.error('%s', outcome['reason'])
                report.finish(error)
            except KeyboardInterrupt as error:
                report.finish(error)
                raise
            finally:
                logger.removeHandler(report.handler)
                report.handler.close()
            with result_lock:
                results.append(outcome)
            logging.info('TABLE_RESULT %s', outcome)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='compare')
        try:
            futures = [executor.submit(worker) for _ in range(min(workers, len(pairs)))]
            for future in as_completed(futures):
                future.result()
        finally:
            stop.set()
            executor.shutdown(wait=True, cancel_futures=True)
        for name, value in completed_stats.items():
            setattr(master.stats, name, value)
        master.configure(table_results=results, completed_table_totals=completed_stats)
        incomplete = any(r['status'] not in ('COMPLETE', 'METADATA_VALIDATED') for r in results)
        master.finish(ConfigurationError('Schema coverage incomplete; see table_results') if incomplete else None)
        return 1 if incomplete else 0
    except (Exception, KeyboardInterrupt) as error:
        write_issue(status='SCHEMA_FAILED', reason=str(error) if isinstance(error, ConfigurationError) else type(error).__name__)
        logging.error('Schema run failed: %s', str(error) if isinstance(error, ConfigurationError) else type(error).__name__)
        for name, value in completed_stats.items():
            setattr(master.stats, name, value)
        master.configure(table_results=results, completed_table_totals=completed_stats)
        master.finish(error)
        return 1
    finally:
        issues_stream.close()
        print(f'Schema issues report: {issues_path.resolve()}')
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        master.handler.close()


class ThreadFilter(logging.Filter):
    def __init__(self, thread_id):
        super().__init__()
        self.thread_id = thread_id

    def filter(self, record):
        return record.thread == self.thread_id


def cancellable(batches, stop):
    for batch in batches:
        if stop.is_set():
            raise ConfigurationError('Run cancelled')
        yield batch
