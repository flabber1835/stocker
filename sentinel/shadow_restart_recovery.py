"""Resume verified committed shadow state; never certify an unknown worker exit."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sentinel import receipt_authentication, shadow_service_status, shadow_worker_liveness

SCHEMA = 'sentinel.shadow-supervisor-pending/3'
MAX_BYTES = 8192
RECOVERY_SECONDS = 180
PROBE_SECONDS = 120
PROOF_MAX_AGE_SECONDS = 30


class RecoveryRefused(ValueError):
    pass


class ArchiveUncertain(RuntimeError):
    pass


class PendingAttempt(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, populate_by_name=True)
    schema_id: Literal['sentinel.shadow-supervisor-pending/3'] = Field(alias='schema')
    attempt_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    started_at_unix: float = Field(gt=0, allow_inf_nan=False)
    runtime_binding_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    boot_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    supervisor_pid: int = Field(gt=0)
    supervisor_start_ticks: int = Field(ge=0)
    pid_namespace: int = Field(gt=0)


class RecoveryProof(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    session: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    record_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    state_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    runtime_identity_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    runtime_authority_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    system_identifier: str = Field(pattern=r'^[0-9]+$')
    observed_at: AwareDatetime
    authority_effect: Literal['NONE'] = 'NONE'


def _binding():
    return shadow_service_status.binding(os.environ.get('SENTINEL_DATABASE_URL', ''))


def make_pending(attempt: str, supervisor_pid: int) -> dict:
    process = shadow_worker_liveness._process(supervisor_pid)
    value = PendingAttempt(schema=SCHEMA, attempt_id=attempt,
        started_at_unix=datetime.now(timezone.utc).timestamp(),
        runtime_binding_sha256=_binding(), boot_id=shadow_worker_liveness._boot(),
        supervisor_pid=supervisor_pid, supervisor_start_ticks=process['start_ticks'],
        pid_namespace=os.stat('/proc/self/ns/pid').st_ino).model_dump(mode='json', by_alias=True)
    return {**value, 'hmac_sha256': receipt_authentication.sign({'purpose': SCHEMA, 'pending': value})}


def decode_pending(value: dict) -> dict:
    payload = {k: v for k, v in value.items() if k != 'hmac_sha256'}
    parsed = PendingAttempt.model_validate_json(json.dumps(payload))
    if (parsed.model_dump(mode='json', by_alias=True) != payload
            or parsed.runtime_binding_sha256 != _binding()
            or not isinstance(value.get('hmac_sha256'), str)
            or not hmac.compare_digest(value['hmac_sha256'],
                receipt_authentication.sign({'purpose': SCHEMA, 'pending': payload}))):
        raise RecoveryRefused('interrupted attempt identity is not authenticated')
    return value


def _raw(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
            raise RecoveryRefused('incident file is not a bounded unaliased regular file')
        value = os.read(fd, MAX_BYTES + 1)
        if len(value) > MAX_BYTES:
            raise RecoveryRefused('incident file exceeds its bound')
        return value
    finally:
        os.close(fd)


def _sync(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def owner(state: Path):
    """Workers inherit this descriptor, fencing replacement of an orphan."""
    state.mkdir(parents=True, exist_ok=True)
    if state.is_symlink():
        raise RecoveryRefused('shadow state directory is aliased')
    fd = os.open(state/'shadow-supervisor-owner.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RecoveryRefused('publisher owner file is aliased')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        os.close(fd)


def eligible(state: Path) -> dict | None:
    critical = state/shadow_service_status.CRITICAL_NAME
    if os.path.lexists(critical):
        return None
    raw = _raw(state/shadow_service_status.PENDING_NAME)
    value = decode_pending(json.loads(raw))
    if value['started_at_unix'] > datetime.now(timezone.utc).timestamp() + 5:
        raise RecoveryRefused('interrupted attempt is future dated')
    # Acquiring the inherited owner lock proves all previous owned processes
    # released it. Independently reject a still-matching old supervisor.
    if (value['boot_id'] == shadow_worker_liveness._boot()
            and value['pid_namespace'] == os.stat('/proc/self/ns/pid').st_ino):
        try:
            process = shadow_worker_liveness._process(value['supervisor_pid'])
        except (OSError, ValueError):
            process = None
        if process and process['start_ticks'] == value['supervisor_start_ticks']:
            raise RecoveryRefused('previous publisher is still alive')
    if shadow_worker_liveness.matches(state/shadow_service_status.PENDING_NAME):
        return None
    return {'attempt_id': value['attempt_id'], 'marker_sha256': hashlib.sha256(raw).hexdigest()}


def verify(config) -> dict:
    """Use the sole canonical reader in a bounded, read-only connection."""
    from sentinel import rolling_runtime, shadow_observation
    from sentinel.feed import calendar, store
    if not config.operational_source_only:
        raise RecoveryRefused('automatic restart requires deployed rolling inputs')
    conn = store.connect(config.database_url, connect_timeout=3, statement_timeout_ms=10000)
    conn.read_only = True
    try:
        result = rolling_runtime.status(conn, observation_id=config.observation_id,
                                       starting_cash=config.starting_cash)
        now = datetime.now(timezone.utc)
        if (result is None or result.shadow_verdict != shadow_observation.SHADOW_GO
                or result.verification != shadow_observation.VERIFIED
                or result.session != calendar.latest_closed_session(now)
                or result.sessions_lag != 0):
            raise RecoveryRefused('current committed shadow is not verified')
        if conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on':
            raise RecoveryRefused('restart proof connection is not read only')
        system_id = conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
        return RecoveryProof(session=result.session, record_sha256=result.record_sha256,
            state_sha256=result.state.state_hash, runtime_identity_sha256=result.runtime_identity_sha256,
            runtime_authority_sha256=result.runtime_authority_sha256,
            system_identifier=system_id, observed_at=now).model_dump(mode='json')
    finally:
        conn.rollback()
        conn.close()


def probe(config) -> dict:
    from sentinel.dependency_availability import database_unavailable, local_contention
    try:
        return {'status': 'VERIFIED', 'proof': verify(config)}
    except Exception as exc:
        return {'status': 'WAITING' if database_unavailable(exc) or local_contention(exc) else 'REFUSED',
                'reason': type(exc).__name__}


def archive(state: Path, proof: dict, expected_marker_sha256: str) -> dict:
    """Keep the unknown attempt and an independently authenticated state proof."""
    from sentinel.feed import calendar
    verified = RecoveryProof.model_validate_json(json.dumps(proof))
    now = datetime.now(timezone.utc)
    if (not 0 <= (now-verified.observed_at).total_seconds() <= PROOF_MAX_AGE_SECONDS
            or verified.session != calendar.latest_closed_session(now)):
        raise RecoveryRefused('restart proof is no longer current')
    selected = eligible(state)
    if not selected or selected['marker_sha256'] != expected_marker_sha256:
        raise RecoveryRefused('interrupted attempt cannot be archived')
    pending = state/shadow_service_status.PENDING_NAME
    raw = _raw(pending)
    if hashlib.sha256(raw).hexdigest() != expected_marker_sha256:
        raise RecoveryRefused('selected pending marker changed')
    attempt = decode_pending(json.loads(raw))
    marker_sha = hashlib.sha256(raw).hexdigest()
    parent = state/'shadow-restart-incidents'
    if parent.is_symlink():
        raise RecoveryRefused('incident directory is aliased')
    parent.mkdir(exist_ok=True)
    target = parent/attempt['attempt_id']
    if target.is_symlink():
        raise RecoveryRefused('incident attempt directory is aliased')
    target.mkdir(exist_ok=True)
    payload = {'schema': 'sentinel.shadow-restart-recovery/1',
        'attempt_id': attempt['attempt_id'], 'marker_sha256': marker_sha,
        'worker_outcome': 'UNKNOWN', 'state_outcome': 'VERIFIED', 'proof': proof}
    receipt = target/'receipt.json'
    if receipt.exists():
        existing = json.loads(_raw(receipt))
        previous = existing['receipt']
        if (not hmac.compare_digest(existing['hmac_sha256'], receipt_authentication.sign(previous))
                or {k: v for k, v in previous.items() if k != 'proof'} !=
                   {k: v for k, v in payload.items() if k != 'proof'}
                or {k: v for k, v in previous['proof'].items() if k != 'observed_at'} !=
                   {k: v for k, v in proof.items() if k != 'observed_at'}):
            raise RecoveryRefused('saved restart proof changed')
    else:
        encoded = (json.dumps({'receipt': payload,
            'hmac_sha256': receipt_authentication.sign(payload)}, sort_keys=True)+'\n').encode()
        fd = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
    _sync(target)
    _sync(parent)
    if os.path.lexists(state/shadow_service_status.CRITICAL_NAME) or _raw(pending) != raw:
        raise RecoveryRefused('incident marker changed during verification')
    archived = target/pending.name
    if os.path.lexists(archived):
        raise RecoveryRefused('incident archive already exists')
    pending.rename(archived)
    _sync(target)
    _sync(state)
    shadow_worker_liveness.clear()
    return {'attempt_id': attempt['attempt_id'], 'marker_sha256': marker_sha,
            'session': verified.session, 'worker_outcome': 'UNKNOWN', 'state_outcome': 'VERIFIED'}
