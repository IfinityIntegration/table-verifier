"""Incremental difference reports and safe, per-execution audit summaries."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from comparator.models import Statistics
from dataclasses import asdict
from comparator.table_comparator import compare_streams


class ReportRun:
    def __init__(self, output='logs'):
        self.started = perf_counter()
        self.start_time = datetime.now(timezone.utc)
        self.execution_id = self.start_time.strftime('%Y_%m_%d_%H%M%S') + '_' + uuid4().hex[:12]
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f'comparison_{self.execution_id}.log'
        self.stats = Statistics()
        self.metadata = {'postgres_table': None, 'oracle_table': None, 'comparison_mode': 'stream'}
        self.handler = logging.FileHandler(self.path, mode='x', encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        self.logger = logging.getLogger(f'comparison.{self.execution_id}')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.addHandler(self.handler)
        self.finished = False
        self.last_progress = perf_counter()
        self.events = 0
        self.logger.info('execution_id=%s start_time=%s mode=stream', self.execution_id, self.start_time.isoformat())

    def configure(self, **metadata):
        self.metadata.update(metadata)
        self.logger.info('execution_id=%s comparison settings=%s', self.execution_id, json.dumps(metadata))

    @staticmethod
    def cell(value):
        # JSON encoding preserves NULL, types, embedded delimiters and newlines.
        return json.dumps(value, ensure_ascii=True, allow_nan=False)

    def emit(self, event):
        status = event['status']
        self.events += 1
        if status != 'MISSING_IN_POSTGRES':
            self.stats.postgres_total += 1
        if status != 'MISSING_IN_ORACLE':
            self.stats.oracle_total += 1
        field = {'MATCHED': 'matched', 'VALUE_MISMATCH': 'value_mismatches',
                 'MISSING_IN_POSTGRES': 'missing_in_postgres', 'MISSING_IN_ORACLE': 'missing_in_oracle'}[status]
        setattr(self.stats, field, getattr(self.stats, field) + 1)
        if status != 'MATCHED':
            self.logger.info('DIFFERENCE %s', self.cell(event))
        if self.events % 10000 == 0 or perf_counter() - self.last_progress >= 10:
            self.handler.flush()
            self.logger.info('execution_id=%s progress rows_processed=%s', self.execution_id, asdict(self.stats))
            self.last_progress = perf_counter()

    def finish(self, error=None):
        if self.finished:
            return
        end = datetime.now(timezone.utc)
        duration = perf_counter() - self.started
        status = 'failed' if error else 'complete'
        summary = {'execution_id': self.execution_id, 'start_time': self.start_time.isoformat(),
                   'end_time': end.isoformat(), 'duration': duration, **self.metadata,
                   **asdict(self.stats), 'status': status}
        if error:
            # Never include arbitrary exception text, locals or driver connection details.
            summary['error_type'] = type(error).__name__
            logging.error('execution_id=%s failed exception_type=%s', self.execution_id, type(error).__name__)
        self.logger.log(logging.ERROR if error else logging.INFO, 'SUMMARY %s', self.cell(summary))
        self.handler.flush()
        self.logger.removeHandler(self.handler)
        self.handler.close()
        self.finished = True
        print('\nComparison ' + ('failed (partial counts)' if error else 'completed'))
        for name, count in asdict(self.stats).items():
            print(f'{name.replace("_", " ").capitalize()}: {count:,}')
        print(f'Duration: {duration:.3f} seconds')
        print(f'Log: {self.path.resolve()}')



def run_comparison(pg_batches, ora_batches, columns, key_count, report):
    return compare_streams(pg_batches, ora_batches, columns, key_count, report.emit)
