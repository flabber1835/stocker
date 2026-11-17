"""Bounded display evidence from the owning fenced PAPER activation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import tempfile

import psycopg

from sentinel import local_paper, receipt_authentication
from sentinel.feed import calendar
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment


SCHEMA = 'sentinel.activation-native-fee-wait/1'
FILENAME = 'activation-native-fee-wait.json'
FRESHNESS = timedelta(seconds=210)
MAX_BYTES = 4096
_DIGEST = re.compile(r'[0-9a-f]{64}')
_DIGEST_KEYS = (
    'SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256',
    'SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256',
    'SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256',
    'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256',
)
_FIELDS = frozenset({'schema', 'decision_session', 'observed_at', 'deadline',
                     'valid_until', 'certificate_sha256', 'control_generation', 'subject_sha256'})


@dataclass(frozen=True)
class ActivationFeeWait:
    decision_session: date
    observed_at: datetime
    deadline: datetime
    valid_until: datetime
    certificate_sha256: str
    control_generation: int


def _target(state_dir):
    return Path(state_dir if state_dir is not None else
                os.environ.get('SENTINEL_STATE_DIR', '/var/lib/sentinel')) / FILENAME


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _sign(value):
    return receipt_authentication.sign({'purpose': SCHEMA, 'activation_fee_wait': value})


def _utc(value):
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(instant, datetime) or instant.utcoffset() != timedelta(0):
        raise ValueError('activation fee wait requires a UTC clock')
    if isinstance(value, str) and value not in (instant.isoformat(), instant.isoformat().replace('+00:00', 'Z')):
        raise ValueError('activation fee wait clock is not canonical')
    return instant


def _session(value):
    session = date.fromisoformat(value) if isinstance(value, str) else value
    if type(session) is not date or isinstance(value, str) and value != session.isoformat():
        raise ValueError('activation fee wait session is not canonical')
    return session


def _subject(conn, session, certificate):
    """Read the fence and latest publication in a single database snapshot."""
    mode = os.environ.get('SENTINEL_REVIEWED_DEPLOYMENT_MODE', '')
    commit = os.environ.get('SENTINEL_GIT_COMMIT', '')
    image = os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST', '')
    inputs = [os.environ.get(key, '') for key in _DIGEST_KEYS]
    expected_account = os.environ.get(local_paper.ACCOUNT_ENV, '')
    endpoint = TradingEndpoint.parse(os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets'))
    if (mode != 'dual' or os.environ.get(local_paper.MODE_ENV) != local_paper.MODE
            or os.environ.get(local_paper.BACKUP_POLICY_ENV) != local_paper.BACKUP_POLICY
            or not re.fullmatch(r'PA[A-Za-z0-9]+', expected_account)
            or not re.fullmatch(r'[0-9a-f]{40}', commit)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', image)
            or not all(_DIGEST.fullmatch(value) for value in inputs)
            or endpoint.environment is not TradingEnvironment.PAPER
            or not isinstance(certificate, str) or not _DIGEST.fullmatch(certificate)):
        raise ValueError('activation fee wait has no reviewed PAPER identity')
    with conn.transaction():
        row = conn.execute(
            "SELECT c.enabled,c.kill_switch_engaged,c.generation,a.active_certificate_sha256,"
            " b.deployment_id,b.broker_account_id,b.takeover_epoch,"
            " s.system_identifier::text,current_database(),pg_postmaster_start_time(),"
            " p.version,p.window_end,p.tableoid::text,p.xmin::text,p.ctid::text "
            "FROM sentinel_automation_control c CROSS JOIN sentinel_execution_authority_state a "
            "CROSS JOIN sentinel_account_binding b CROSS JOIN pg_control_system() s "
            "CROSS JOIN (SELECT version,window_end,tableoid,xmin,ctid FROM sentinel_corpus_publications "
            "ORDER BY version DESC LIMIT 1) p "
            "WHERE c.id=1 AND a.id=1 AND b.id=1 AND b.broker='alpaca' "
            "AND b.ownership_state='SENTINEL_OWNED'"
        ).fetchone()
    if row is None:
        raise ValueError('activation fee wait has no bound fence or publication')
    enabled, killed, generation, active_certificate, deployment, account, takeover_epoch, *scope = row
    system, database, postmaster_start, version, frontier, table, xmin, ctid = scope
    if (enabled is not False or killed is not True or type(generation) is not int or generation < 1
            or active_certificate != certificate or account != expected_account or frontier != session):
        raise ValueError('activation fee wait fence or publication changed')
    material = [mode, commit, image, inputs, deployment, account, takeover_epoch, system, database,
                _utc(postmaster_start.astimezone(timezone.utc)).isoformat(), version, frontier.isoformat(), table, xmin, ctid]
    return generation, hashlib.sha256(_canonical(material)).hexdigest()


def _eligible(wait, now):
    return (wait.observed_at <= now < wait.valid_until
            and wait.valid_until == min(wait.deadline, wait.observed_at + FRESHNESS)
            and calendar.latest_closed_session(now) == wait.decision_session.isoformat()
            and wait.deadline <= calendar.session_window(calendar.next_session(wait.decision_session))[0])


def _read(target):
    if target.is_symlink():
        raise ValueError('activation fee wait file is aliased')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(target, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('activation fee wait file is aliased')
        raw = stream.read(MAX_BYTES + 1)
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('activation fee wait record exceeds its bound')
    envelope = json.loads(raw)
    if (not isinstance(envelope, dict) or set(envelope) != {'value', 'signature'}
            or not isinstance(envelope['value'], dict) or set(envelope['value']) != _FIELDS
            or envelope['value']['schema'] != SCHEMA or not isinstance(envelope['signature'], str)
            or not _DIGEST.fullmatch(envelope['signature'])
            or raw != _canonical(envelope) or not hmac.compare_digest(envelope['signature'], _sign(envelope['value']))):
        raise ValueError('activation fee wait record is not authenticated')
    value = envelope['value']
    certificate = value['certificate_sha256']
    generation = value['control_generation']
    subject = value['subject_sha256']
    if (not isinstance(certificate, str) or not _DIGEST.fullmatch(certificate)
            or type(generation) is not int or generation < 1
            or not isinstance(subject, str) or not _DIGEST.fullmatch(subject)):
        raise ValueError('activation fee wait identity is malformed')
    return ActivationFeeWait(_session(value['decision_session']), _utc(value['observed_at']),
                             _utc(value['deadline']), _utc(value['valid_until']), certificate, generation), subject


def publish_owned(conn, *, decision_session, deadline, certificate_sha256, now=None, state_dir=None):
    """Observe an exact typed fee wait from the existing activation owner."""
    try:
        instant = _utc(now if now is not None else datetime.now(timezone.utc))
        session, cutoff = _session(decision_session), _utc(deadline)
        generation, subject = _subject(conn, session, certificate_sha256)
        wait = ActivationFeeWait(session, instant, cutoff, min(cutoff, instant + FRESHNESS),
                                 certificate_sha256, generation)
        if not _eligible(wait, instant):
            return None
        value = dict(schema=SCHEMA, decision_session=session.isoformat(), observed_at=instant.isoformat(),
                     deadline=cutoff.isoformat(), valid_until=wait.valid_until.isoformat(),
                     certificate_sha256=certificate_sha256, control_generation=generation, subject_sha256=subject)
        raw = _canonical(dict(value=value, signature=_sign(value)))
        target = _target(state_dir)
        descriptor, name = tempfile.mkstemp(dir=target.parent, prefix='.activation-native-fee-')
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return wait
    except (OSError, ValueError, psycopg.Error, calendar.CalendarUnavailable):
        return None


def read_owned(conn, *, now, state_dir=None) -> ActivationFeeWait | None:
    """Consume the same-subject display observation without awarding readiness."""
    try:
        wait, subject = _read(_target(state_dir))
        if (_eligible(wait, _utc(now)) and
                _subject(conn, wait.decision_session, wait.certificate_sha256) == (wait.control_generation, subject)):
            return wait
    except (OSError, ValueError, psycopg.Error, calendar.CalendarUnavailable):
        pass
    return None


def clear_owned(conn, *, decision_session, certificate_sha256, state_dir=None) -> None:
    """Withdraw this owner's marker after convergence or a terminal refusal."""
    try:
        target = _target(state_dir)
        wait, subject = _read(target)
        if (wait.decision_session == _session(decision_session) and wait.certificate_sha256 == certificate_sha256
                and _subject(conn, wait.decision_session, wait.certificate_sha256) == (wait.control_generation, subject)):
            target.unlink(missing_ok=True)
    except (OSError, ValueError, psycopg.Error, calendar.CalendarUnavailable):
        pass
