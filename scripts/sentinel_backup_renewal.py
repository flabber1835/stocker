"""Publication-owned scheduling and closed, non-authoritative pass diagnostics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import threading
import time

PASS_PREFIX = 'maintenance_pass_result:'
REFRESH_PREFIX = 'maintenance_refresh_result:'
SCHEMA = 'sentinel.maintenance-pass-result/2'
TTL_SECONDS = 600
INTERVAL_SECONDS = 300
PROOF_REFRESH_LEAD_SECONDS = 150
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


def byte_renewal_at(publication_at, proof, primary_uptime):
    """Map qualified original byte-proof uptime to a scheduling instant."""
    if proof.get('schema') != 'sentinel.maintenance-integrity/1':
        return None
    completed = proof.get('integrity_completed_uptime')
    observed = proof.get('integrity_observed_uptime')
    limit = proof.get('integrity_max_reuse_seconds')
    if (limit != INTERVAL_SECONDS or any(type(stamp) not in {int, float} or not math.isfinite(stamp)
            for stamp in (completed, observed)) or not 0 <= completed <= observed < completed+limit):
        return None
    if isinstance(primary_uptime, str):
        try:
            primary_uptime = float(primary_uptime)
        except ValueError:
            return None
    if (type(primary_uptime) not in {int, float} or not math.isfinite(primary_uptime)
            or primary_uptime < observed):
        return None
    age = primary_uptime - completed
    due_in = max(0, limit - PROOF_REFRESH_LEAD_SECONDS - age)
    return (timestamp(publication_at) + timedelta(seconds=due_in)).isoformat()


def validate_result(value):
    if (not isinstance(value,dict) or set(value)-{'byte_renewal_at'} != {'schema','outcome','phase','code',
            'cause_type','publication_at','elapsed_seconds','failure','started_at','finished_at'}
            or value['schema'] != SCHEMA or value['outcome'] not in OUTCOMES
            or value['phase'] not in PHASES or value['code'] not in CODES
            or value['cause_type'] not in {'NONE','Refused','OSError','ValueError','KeyError',
                'TypeError','UNKNOWN'} or type(value['elapsed_seconds']) not in {int,float}
            or not math.isfinite(value['elapsed_seconds']) or value['elapsed_seconds'] < 0):
        raise ValueError('invalid maintenance pass result')
    if timestamp(value['finished_at']) < timestamp(value['started_at']):
        raise ValueError('maintenance pass timing regressed')
    if value['publication_at'] is not None: timestamp(value['publication_at'])
    if 'byte_renewal_at' in value:
        byte_due = timestamp(value['byte_renewal_at'])
        if value['publication_at'] is None or not 0 <= (
                byte_due-timestamp(value['publication_at'])).total_seconds() <= INTERVAL_SECONDS:
            raise ValueError('byte renewal lacks its bounded publication clock')
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
           cause_type='NONE', failure=None,started_at=None,finished_at=None,byte_due_at=None):
    if started_at is None and finished_at is None and elapsed_seconds == 0:
        started_at = finished_at = datetime.now(timezone.utc).isoformat()
    if started_at is None or finished_at is None:
        raise ValueError('maintenance owner timing is required')
    value = dict(schema=SCHEMA,outcome=outcome,phase=phase,code=code,
        publication_at=publication_at,elapsed_seconds=elapsed_seconds,cause_type=cause_type,failure=failure,
        started_at=started_at,finished_at=finished_at)
    if byte_due_at is not None:
        value['byte_renewal_at'] = byte_due_at
    return validate_result(value)


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
        self.byte_due_at = None
        self.byte_publication_at = None
        self.deadline = None
        self.due = clock()
        self.retries = 0
        if publication_at is not None: self.accept(publication_at)

    def accept(self, publication_at, *, byte_due_at=None, own_publication=False):
        stamp = timestamp(publication_at)
        with self.lock:
            now, wall = self.clock(), self.wallclock()
            if stamp > wall: raise ValueError('future maintenance publication')
            if self.publication_at is not None:
                previous = timestamp(self.publication_at)
                if stamp < previous: raise ValueError('maintenance publication clock regressed')
                if stamp == previous and (byte_due_at is None or self.byte_publication_at == publication_at):
                    return
            age = (wall-stamp).total_seconds()
            self.publication_at = publication_at
            if byte_due_at is not None or own_publication:
                self.byte_due_at = byte_due_at
                self.byte_publication_at = publication_at if byte_due_at is not None else None
            byte_due = timestamp(self.byte_due_at) if self.byte_due_at is not None else None
            self.deadline = now+TTL_SECONDS-age
            due = stamp+timedelta(seconds=INTERVAL_SECONDS)
            if byte_due is not None:
                due = min(due, byte_due)
            self.due = now + (due-wall).total_seconds()
            self.retries = 0

    def publication(self):
        with self.lock: return self.publication_at

    def timing(self):
        with self.lock:
            return {'publication_at': self.publication_at, 'byte_due_at': (
                self.byte_due_at if self.byte_publication_at == self.publication_at else None)}

    def next_at(self):
        with self.lock: return self.due

    def prime_due(self, byte_due_at):
        """Bring forward the first owned freshness check during bulk work."""
        with self.lock:
            self.due = min(self.due, self.clock() + (timestamp(byte_due_at)-self.wallclock()).total_seconds())

    def consume(self, value):
        validate_result(value)
        with self.lock:
            previous = self.publication_at
            if value['publication_at'] is not None:
                self.accept(value['publication_at'], byte_due_at=value.get('byte_renewal_at'),
                            own_publication=value['outcome'] == 'SUCCESS')
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
