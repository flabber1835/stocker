"""Presentation-only incident summaries of authenticated review records."""

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256

from sentinel.panel.presentation import _COPY, _STEPS


@dataclass(frozen=True)
class Entry:
    key: str
    kind: str
    records: tuple[dict, ...]
    started_at: str | None = None
    recovered_at: str | None = None


@dataclass
class _Incident:
    key: str
    started_at: str | None
    records: list[dict] = field(default_factory=list)
    recovered_at: str | None = None
    latest_index: int = 0


_LABELS = {
    'backend_sources': 'Dashboard data sources',
    'dashboard_read_unavailable': 'Dashboard data collection',
    'no_current_operation': 'Current operating evidence',
    'operational_projection': 'Dashboard health checks',
    'completed_trading_run': 'Completed trading run',
    'trading_run': 'Trading run',
}
_DISPATCHER = 'alert_dispatcher'
_WAITING = 'WAITING_OPEN'
_SCHEDULED_MIRROR = 'PAPER NOT VERIFIED · SCHEDULED · HISTORICAL MIRROR WARNING'
_SCHEDULE = {
    'automation_cycle': (_WAITING, 'AUTOMATION_WAITING_OPEN'),
    'automation_step_open': (_WAITING, 'AUTOMATION_OPEN'),
    'paper_reconciliation': (_SCHEDULED_MIRROR, None),
}
_SCHEDULE_KEYS = frozenset(_SCHEDULE)
_SCHEDULE_PROOFS = {
    key: (sha256(value.encode('utf-8')).hexdigest(), phase)
    for key, (value, phase) in _SCHEDULE.items()
}


def condition_label(key):
    """Translate stock row keys. The caller escapes retained legacy text."""
    if key.startswith('missing:'):
        return 'Missing check · ' + condition_label(key.removeprefix('missing:'))
    copy = _COPY.get(key)
    if key.startswith('automation_step_'):
        copy = _STEPS.get(key.removeprefix('automation_step_'))
    return copy[0] if copy else _LABELS.get(key, key.replace('_', ' '))


def _timestamp(raw):
    if isinstance(raw, str):
        try:
            value = datetime.fromisoformat(raw)
            if value.utcoffset() is not None:
                return value
        except (ValueError, OverflowError):
            pass
    return None


def _keys(raw):
    if isinstance(raw, list):
        return {key for key in raw if isinstance(key, str) and key}
    return set()


def _evidence(details):
    evidence = details.get('evidence')
    if not isinstance(evidence, dict):
        return {}
    return {key: item for key, item in evidence.items() if isinstance(item, dict)}


def _dispatcher_observation(event, evidence):
    details = event['details']
    alert = evidence.get(_DISPATCHER, {})
    if (event['kind'] not in {'REVIEW', 'FAILED', 'RECOVERED'} or
            _DISPATCHER not in _keys(details.get('conditions')) | _keys(details.get('previous')) or
            alert.get('code') != 'ROW_CONDITION'):
        return None
    sample = _timestamp(alert.get('sampled_at'))
    observed = _timestamp(alert.get('as_of'))
    at = _timestamp(event['at'])
    status = (alert.get('raw_status'), alert.get('effective_status'), alert.get('recovery_phase'))
    if (sample is None or observed is None or at is None or not observed <= sample <= at or
            status not in (('warn', 'warn', 'ALERT_TRANSPORT'),
                           ('warn', 'fail', 'ALERT_TRANSPORT'),
                           ('fail', 'fail', None), ('ok', 'ok', None))):
        return None
    return at, sample


def _legacy_schedule_observation(event, evidence, keys):
    """Recognize only the recorded scheduled mirror and its two matching waits."""
    if (event['kind'] not in {'REVIEW', 'RECOVERED'} or
            'transition' in event['details'] or not _SCHEDULE_KEYS <= keys):
        return None
    at = _timestamp(event['at'])
    cycle = evidence.get('automation_cycle', {})
    step = evidence.get('automation_step_open', {})
    mirror = evidence.get('paper_reconciliation', {})
    sample = _timestamp(cycle.get('sampled_at'))
    cycle_time = _timestamp(cycle.get('as_of'))
    mirror_time = _timestamp(mirror.get('as_of'))
    lifecycle = _timestamp(cycle.get('original_valid_until'))
    mirror_until = _timestamp(mirror.get('original_valid_until'))
    if (None in (at, sample, cycle_time, mirror_time, lifecycle, mirror_until) or
            not cycle_time <= sample <= at or not mirror_time <= sample < mirror_until < lifecycle or
            _timestamp(step.get('as_of')) != cycle_time or
            _timestamp(step.get('original_valid_until')) != lifecycle or
            mirror_until.microsecond != 999_999):
        return None
    for key, (digest, phase) in _SCHEDULE_PROOFS.items():
        fact = evidence.get(key, {})
        if (fact.get('code') != 'ROW_CONDITION' or fact.get('raw_status') != 'warn' or
                fact.get('effective_status') != 'warn' or fact.get('value_sha256') != digest or
                fact.get('recovery_phase') != phase or _timestamp(fact.get('sampled_at')) != sample):
            return None
    return at, sample


def _changes(event, dispatcher_observations):
    details = event['details']
    kind = event['kind']
    if kind not in {'REVIEW', 'FAILED', 'RECOVERED'} or any(
            key in details for key in ('component', 'reason', 'alert_ids', 'attempt')):
        return []
    conditions = _keys(details.get('conditions'))
    previous = _keys(details.get('previous'))
    evidence = _evidence(details)
    legacy_schedule = _legacy_schedule_observation(event, evidence, conditions | previous)
    context = legacy_schedule in dispatcher_observations
    if context:
        conditions -= _SCHEDULE_KEYS
        previous -= _SCHEDULE_KEYS
    keys = conditions - previous
    # A legacy full-set delta also carried evidence for rows leaving the set.
    # For the newer level-specific records, unrelated previous keys have no evidence.
    keys |= {key for key in previous - conditions if kind == 'RECOVERED' or key in evidence}
    if kind == 'RECOVERED' and not keys:
        keys = conditions | previous
    changes = []
    for key in sorted(keys):
        status = evidence.get(key, {}).get('effective_status')
        resolved = (status == 'ok' and (kind == 'RECOVERED' or key not in conditions)
                    or kind == 'RECOVERED' and (details.get('transition') == 'RESOLVED'
                    or status is None and key == 'dashboard_read_unavailable'))
        opens = kind in {'FAILED', 'REVIEW'} and key in conditions
        changes.append((key, opens, resolved))
    if context and not any(key == _DISPATCHER for key, _, _ in changes):
        changes.append((_DISPATCHER, False, False))
    return changes


def summarize(events):
    """Group only the given bounded page; the original records stay intact."""
    dispatcher_observations = {
        observed for event in events
        if (observed := _dispatcher_observation(event, _evidence(event['details']))) is not None
    }
    active = {}
    entries = []
    for index, event in enumerate(reversed(events)):
        at = event['at']
        changes = _changes(event, dispatcher_observations)
        if not changes:
            entries.append((index, Entry('', event['kind'], (event,), started_at=at)))
        for key, opens, resolved in changes:
            incident = active.get(key)
            if incident is None or (incident.recovered_at is not None and incident.recovered_at != at):
                incident = _Incident(key, at if opens else None)
                active[key] = incident
                entries.append(incident)
            incident.records.append(event)
            incident.latest_index = index
            if resolved:
                incident.recovered_at = at
    ordered = [
        (item.latest_index, Entry(item.key, 'INCIDENT', tuple(reversed(item.records)),
                                  item.started_at, item.recovered_at))
        if isinstance(item, _Incident) else item
        for item in entries
    ]
    return [entry for _, entry in sorted(ordered, key=lambda item: item[0], reverse=True)]
