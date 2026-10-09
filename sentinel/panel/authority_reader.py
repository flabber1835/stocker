"""One finite read-only financial observation; retained values are presentation."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import pickle
from threading import Lock, Thread
import time

from sentinel import supervisor_io
from sentinel.panel import model

DEADLINE_SECONDS = 300
RETRY_SECONDS = 30
MAX_BYTES = 4 * 1024
FRESH_SECONDS = 30


def _observe(database_url, include_paper):
    from sentinel.panel.sources import _dual_authority_rows
    rows, details, history, errors = _dual_authority_rows(
        database_url, now=datetime.now(timezone.utc), include_paper=include_paper)
    if details or history or len(rows) > 4:
        raise ValueError('unexpected financial observer shape')
    value = {'rows': [asdict(row) for row in rows], 'errors': errors,
             'observed_at': datetime.now(timezone.utc)}
    if (len(json.dumps(value, default=str, allow_nan=False).encode()) > MAX_BYTES
            or len(pickle.dumps(value)) > MAX_BYTES):
        raise ValueError('financial observer result exceeds bound')
    return value


def _key(database_url, include_paper):
    environment = {k: v for k, v in os.environ.items() if k.startswith('SENTINEL_')}
    return hashlib.sha256(json.dumps([database_url, include_paper, environment],
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _unknown(include_paper, detail, retained=None):
    values = {row.key: row for row in retained or ()}
    rows = [model.shadow_verification_row(
        verdict=None, verification=None, session=None, error=detail, unreadable=True)]
    for key, label in (('shadow_nav', 'Certified shadow NAV'),
                       ('shadow_return', 'Certified strategy return')):
        prior = values.get(key)
        metric = model.shadow_metric_row(key, label,
            prior.value if prior else None, verified=False,
            detail=('LAST KNOWN · '+detail) if prior else detail)
        rows.append(replace(metric, as_of=prior.as_of) if prior else metric)
    if include_paper:
        rows.append(model.paper_reconciliation_row(state='UNKNOWN', error=detail))
    return rows, {}, [], ['financial verification: '+detail]


class Reader:
    def __init__(self, *, runner=None, clock=time.monotonic):
        self.runner = runner or supervisor_io.run
        self.clock = clock
        self.lock = Lock()
        self.pending = None
        self.answer = None
        self.retained = None
        self.configuration = None
        self.last_attempt = float('-inf')

    def _work(self, key, database_url, include_paper):
        try:
            value = self.runner(_observe, database_url, include_paper,
                timeout=DEADLINE_SECONDS, start_method='spawn')
            answer = (key, value, None)
        except Exception as exc:
            # No dependency exception (which might include private config) is
            # echoed. Its classified type is enough for the operator.
            answer = (key, None, type(exc).__name__)
        with self.lock:
            self.answer = answer
            self.pending = None

    def read(self, database_url, *, include_paper=True):
        key = _key(database_url, include_paper)
        with self.lock:
            if key != self.configuration:
                self.configuration = key
                self.retained = None
                self.last_attempt = float('-inf')
            detail = 'full retained financial verification awaits its next bounded check'
            if self.answer is not None:
                completed_key, value, error = self.answer
                self.answer = None  # A positive observation is delivered once.
                if completed_key == key:
                    if error is not None:
                        detail = 'financial observer failed: '+error
                    else:
                        try:
                            expected = {'shadow_verification', 'shadow_nav', 'shadow_return'}
                            if include_paper:
                                expected.add('paper_reconciliation')
                            if (not isinstance(value, dict)
                                    or set(value) != {'rows', 'errors', 'observed_at'}
                                    or not isinstance(value['rows'], list)
                                    or len(value['rows']) != len(expected)
                                    or {row['key'] for row in value['rows']} != expected
                                    or not isinstance(value['errors'], list)
                                    or len(value['errors']) > 4
                                    or any(not isinstance(error, str) or len(error) > 1000
                                           for error in value['errors'])):
                                raise ValueError('observer shape is incomplete')
                            for row in value['rows']:
                                if (not isinstance(row, dict)
                                        or any(not isinstance(row.get(field), str)
                                               for field in ('key', 'label', 'value', 'status', 'detail'))
                                        or row['status'] not in {model.OK, model.PENDING, model.WARN,
                                                                 model.FAIL, model.UNKNOWN}
                                        or any(len(row[field]) > 1000
                                               for field in ('label', 'value', 'detail'))):
                                    raise ValueError('observer row is malformed')
                            observed = value['observed_at']
                            age = datetime.now(timezone.utc)-observed
                            if not timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):
                                raise ValueError('observer result is not fresh')
                            rows = [replace(model.Row(**row), as_of=observed,
                                freshness=timedelta(seconds=FRESH_SECONDS),
                                required_current=True) for row in value['rows']]
                            if any(row.key == 'shadow_verification'
                                   and row.status == model.OK for row in rows):
                                self.retained = rows
                            return rows, {}, [], value['errors']
                        except (KeyError, TypeError, ValueError):
                            detail = 'financial observer result is malformed or stale'
            if self.pending is None and self.clock()-self.last_attempt >= RETRY_SECONDS:
                self.last_attempt = self.clock()
                self.pending = Thread(target=self._work,
                    args=(key, database_url, include_paper), daemon=True,
                    name='sentinel-panel-financial-observer')
                self.pending.start()
            if self.pending is not None:
                detail = 'full retained financial verification is running'
            return _unknown(include_paper, detail, self.retained)


reader = Reader()
