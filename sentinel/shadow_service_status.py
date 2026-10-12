"""Expiring publisher liveness; never financial or recovery authority."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA = 'sentinel.shadow-service-status/1'
NAME = 'shadow-service-status.json'
MAX_BYTES = 8192
MAX_AGE_SECONDS = 60
PENDING_NAME = 'shadow-supervisor-pending.json'
CRITICAL_NAME = 'shadow-supervisor-critical.json'


class Status(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, populate_by_name=True)
    schema_id: Literal['sentinel.shadow-service-status/1'] = Field(default=SCHEMA, alias='schema')
    binding_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    incarnation: str = Field(pattern=r'^[0-9a-f]{32}$')
    state: Literal['RUNNING', 'FENCED', 'STOPPED']
    reason: Literal['IDLE', 'ACTIVE_WORKER', 'CRITICAL_LATCH', 'UNACKNOWLEDGED_WORKER', 'STOPPED']
    observed_at: AwareDatetime
    attempt_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    worker_deadline: AwareDatetime | None = None

    @model_validator(mode='after')
    def require_consistent_state(self):
        if self.observed_at.utcoffset() != timedelta(0):
            raise ValueError('worker observation must use UTC')
        if self.worker_deadline is not None and self.worker_deadline.utcoffset() != timedelta(0):
            raise ValueError('worker deadline must use UTC')
        if self.state == 'RUNNING':
            active = self.reason == 'ACTIVE_WORKER'
            if (self.reason not in {'IDLE', 'ACTIVE_WORKER'}
                    or active != (self.attempt_id is not None)
                    or active != (self.worker_deadline is not None)
                    or active and not self.observed_at <= self.worker_deadline
                        <= self.observed_at+timedelta(seconds=7200)):
                raise ValueError('running worker observation is inconsistent')
        elif self.worker_deadline is not None or (
                self.state == 'FENCED' and self.reason not in {'CRITICAL_LATCH', 'UNACKNOWLEDGED_WORKER'}
                or self.state == 'STOPPED' and self.reason != 'STOPPED'):
            raise ValueError('negative worker observation is inconsistent')
        return self


def binding(database_url: str) -> str:
    git = os.environ.get('SENTINEL_GIT_COMMIT', '')
    image = os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST', '')
    import re
    if (not re.fullmatch('[0-9a-f]{40}', git)
            or not re.fullmatch('sha256:[0-9a-f]{64}', image) or not database_url):
        raise ValueError('reviewed worker binding is unavailable')
    value = [git, image, os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary'), database_url]
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def _raw(path: Path) -> bytes:
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError('worker status exceeds its bound')
    return raw


def pending(path: Path) -> dict | None:
    try:
        raw = _raw(path)
    except FileNotFoundError:
        return None
    return _decode_pending(raw)


def _decode_pending(raw):
    if raw is None:
        return None
    value = json.loads(raw)
    import math
    import re
    if (not isinstance(value, dict)
            or set(value) != {'schema', 'attempt_id', 'started_at_unix'}
            or value['schema'] != 'sentinel.shadow-supervisor-pending/2'
            or not isinstance(value['attempt_id'], str)
            or not re.fullmatch('[0-9a-f]{32}', value['attempt_id'])
            or type(value['started_at_unix']) not in {int, float}
            or not math.isfinite(value['started_at_unix']) or value['started_at_unix'] <= 0):
        raise ValueError('pending worker identity is malformed')
    return value


def _signature(payload):
    from sentinel.receipt_authentication import sign
    return sign({'purpose': SCHEMA, 'status': payload})


def _load(target: Path) -> Status:
    return _decode_status(_raw(target))


def _decode_status(raw) -> Status:
    wrapped = json.loads(raw)
    if (not isinstance(wrapped, dict) or set(wrapped) != {'status', 'hmac_sha256'}
            or not isinstance(wrapped['status'], dict)
            or not isinstance(wrapped['hmac_sha256'], str)
            or not hmac.compare_digest(wrapped['hmac_sha256'], _signature(wrapped['status']))):
        raise ValueError('worker observation authentication failed')
    value = Status.model_validate_json(json.dumps(wrapped['status']))
    if value.model_dump(mode='json', by_alias=True) != wrapped['status']:
        raise ValueError('worker observation shape changed')
    return value


def _write(target: Path, value: Status):
    payload = value.model_dump(mode='json', by_alias=True)
    raw = json.dumps({'status': payload, 'hmac_sha256': _signature(payload)},
                     sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('worker observation exceeds its bound')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.shadow-status-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish(critical: Path, incarnation: str, *, stopped=False, now=None):
    """Runs only inside the supervisor's existing finite dependency observer."""
    from sentinel import shadow_worker_liveness as live
    instant = now or datetime.now(timezone.utc)
    target = critical.with_name(NAME)
    expected = binding(os.environ.get('SENTINEL_DATABASE_URL', ''))
    attempt = pending(critical.with_name(PENDING_NAME))
    attempt_id = attempt['attempt_id'] if attempt else None
    state, reason, deadline = 'RUNNING', 'IDLE', None
    if critical.exists():
        state, reason = 'FENCED', 'CRITICAL_LATCH'
    elif stopped:
        state, reason = 'STOPPED', 'STOPPED'
    elif attempt:
        try:
            prior = _load(target)
        except (OSError, ValueError, TypeError):
            prior = None
        same = (prior is not None and prior.incarnation == incarnation
                and prior.binding_sha256 == expected and prior.attempt_id == attempt_id
                and prior.state == 'RUNNING')
        if live.matches(critical.with_name(PENDING_NAME)):
            active = json.loads(_raw(live.ACTIVE_FILE))
            deadline = instant+timedelta(seconds=active['deadline_monotonic']-time.monotonic())
            if same:
                deadline = min(deadline, prior.worker_deadline)
            reason = 'ACTIVE_WORKER'
        elif (same and timedelta(0) <= instant-prior.observed_at <= timedelta(seconds=MAX_AGE_SECONDS)
              and instant <= prior.worker_deadline):
            return  # Natural child/acknowledgement handoff cannot renew the old proof.
        else:
            state, reason = 'FENCED', 'UNACKNOWLEDGED_WORKER'
    _write(target, Status(binding_sha256=expected, incarnation=incarnation, state=state,
        reason=reason, observed_at=instant, attempt_id=attempt_id, worker_deadline=deadline))


def read(state_dir: Path, database_url: str) -> dict:
    """Bounded, read-only projection; persistent negative markers always win."""
    from sentinel.shadow_service_probe import observe
    return decode_probe(observe(state_dir), database_url)


def decode_probe(snapshot, database_url):
    """Validate the finite snapshot with the unchanged producer contract."""
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {'critical', 'pending', 'status', 'latest_pending'}
            or type(snapshot['critical']) is not bool
            or any(value is not None and (not isinstance(value, bytes) or len(value) > MAX_BYTES)
                   for key, value in snapshot.items() if key != 'critical')):
        raise ValueError('worker snapshot is malformed')
    if snapshot['critical']:
        return {'state': 'FENCED', 'reason': 'CRITICAL_LATCH'}
    attempt = _decode_pending(snapshot['pending'])
    value = _decode_status(snapshot['status'])
    latest = _decode_pending(snapshot['latest_pending'])
    if latest is not None and latest != attempt:
        raise ValueError('durable worker attempt changed during observation')
    if value.binding_sha256 != binding(database_url):
        raise ValueError('worker observation belongs to another runtime')
    if value.state == 'RUNNING' and attempt is not None and value.attempt_id != attempt['attempt_id']:
        raise ValueError('worker observation disagrees with the durable attempt')
    return value.model_dump()
