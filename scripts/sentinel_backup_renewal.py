"""Publication-owned scheduling and closed, non-authoritative pass diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import threading
import time

PASS_PREFIX = 'maintenance_pass_result:'
REFRESH_PREFIX = 'maintenance_refresh_result:'
SCHEMA = 'sentinel.maintenance-pass-result/1'
TTL_SECONDS = 600
INTERVAL_SECONDS = 300
BACKOFF = (1, 2, 5, 10, 20, 30)
PHASES = {'PREFLIGHT','OBSERVE','BASE_BACKUP','VERIFY_CHAIN','PUBLISH_CHAIN',
          'CHECKPOINT','RETENTION','COMPLETE'}
OUTCOMES = {'SUCCESS','RETRYABLE','BLOCKED','STANDBY'}
CODES = {'OK','TARGET_BUSY','CHILD_FAILED','COORDINATOR_REFUSED','UNCLASSIFIED',
         'INVALID_RESULT','BUSY','PROOF_WINDOW_EXPIRED','SELECTION_MOVED','PHYSICAL_UNAVAILABLE',
         'INTEGRITY_REFUSED','POLICY_REFUSED','DATABASE_FAILURE','DEADLINE_EXCEEDED',
         'TRANSPORT_FAILURE','PROTOCOL_FAILURE','INTERNAL_FAILURE'}


def timestamp(value):
    if not isinstance(value,str): raise ValueError('publication timestamp is not text')
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
        raise ValueError('publication timestamp is not UTC')
    return result


def validate_result(value):
    if (not isinstance(value,dict) or set(value) != {'schema','outcome','phase','code',
            'cause_type','publication_at','elapsed_seconds','failure'}
            or value['schema'] != SCHEMA or value['outcome'] not in OUTCOMES
            or value['phase'] not in PHASES or value['code'] not in CODES
            or value['cause_type'] not in {'NONE','Refused','OSError','ValueError','KeyError',
                'TypeError','UNKNOWN'} or type(value['elapsed_seconds']) not in {int,float}
            or not math.isfinite(value['elapsed_seconds']) or value['elapsed_seconds'] < 0):
        raise ValueError('invalid maintenance pass result')
    if value['publication_at'] is not None: timestamp(value['publication_at'])
    failure = value['failure']
    if failure is not None:
        from sentinel_backup_integrity_report import validate_failure
        validate_failure(failure)
        if failure['origin'] != 'HOST' or value['code'] != failure['code'] or value['outcome'] != (
                'RETRYABLE' if failure['retryable'] else 'BLOCKED'):
            raise ValueError('contradictory maintenance failure')
    if value['outcome'] == 'RETRYABLE' and (failure is None or not failure['retryable']):
        raise ValueError('unclassified maintenance retry')
    if value['outcome'] == 'STANDBY' and (value['code'] != 'TARGET_BUSY' or failure is not None):
        raise ValueError('invalid target standby')
    if value['outcome'] == 'SUCCESS' and (value['code'] != 'OK' or value['publication_at'] is None):
        raise ValueError('success without publication')
    return value


def result(*, outcome, phase, code, publication_at=None, elapsed_seconds=0,
           cause_type='NONE', failure=None):
    return validate_result(dict(schema=SCHEMA,outcome=outcome,phase=phase,code=code,
        publication_at=publication_at,elapsed_seconds=elapsed_seconds,cause_type=cause_type,failure=failure))


def emit(value, *, refresh=False):
    print((REFRESH_PREFIX if refresh else PASS_PREFIX)+json.dumps(validate_result(value),
        sort_keys=True,separators=(',',':'),allow_nan=False),flush=True)


def parse(output, *, refresh=False):
    prefix = REFRESH_PREFIX if refresh else PASS_PREFIX
    records = [line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)]
    if len(records) != 1: raise ValueError('missing or ambiguous maintenance result')
    def unique(pairs):
        value = {}
        for key,item in pairs:
            if key in value: raise ValueError('duplicate maintenance result key')
            value[key] = item
        return value
    return validate_result(json.loads(records[0],object_pairs_hook=unique))


class Schedule:
    """A failure never changes an admitted publication's original deadline."""
    def __init__(self, publication_at=None, *, clock=time.monotonic,
                 wallclock=lambda:datetime.now(timezone.utc)):
        self.clock, self.wallclock = clock, wallclock
        self.lock = threading.RLock()
        self.publication_at = None
        self.deadline = None
        self.due = clock()
        self.retries = 0
        if publication_at is not None: self.accept(publication_at)

    def accept(self, publication_at):
        stamp = timestamp(publication_at)
        with self.lock:
            now, wall = self.clock(), self.wallclock()
            if stamp > wall: raise ValueError('future maintenance publication')
            if self.publication_at is not None:
                previous = timestamp(self.publication_at)
                if stamp < previous: raise ValueError('maintenance publication clock regressed')
                if stamp == previous: return
            age = (wall-stamp).total_seconds()
            self.publication_at = publication_at
            self.deadline = now+TTL_SECONDS-age
            self.due = now+INTERVAL_SECONDS-age
            self.retries = 0

    def publication(self):
        with self.lock: return self.publication_at

    def next_at(self):
        with self.lock: return self.due

    def consume(self, value):
        validate_result(value)
        with self.lock:
            previous = self.publication_at
            if value['publication_at'] is not None: self.accept(value['publication_at'])
            now = self.clock()
            if value['outcome'] == 'SUCCESS' or self.publication_at != previous: return
            if (value['outcome'] in {'RETRYABLE','STANDBY'} and self.deadline is not None
                    and now < self.deadline):
                delay = BACKOFF[min(self.retries,len(BACKOFF)-1)]
                self.retries += 1
                self.due = min(now+delay,self.deadline)
            else:
                # Ordinary future passes may establish new evidence, but no
                # rapid retry borrows an expired or unknown proof lifetime.
                self.due = now+INTERVAL_SECONDS

    def delay(self):
        return max(0,self.next_at()-self.clock())
