"""Bound a normal reactivated startup alert without suppressing its producer."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from . import checks, evidence, reactivated_startup
from .host import SERVICES
from .model import DeliveryRefused, digest, require, utcnow


_HISTORY_GROUPS = frozenset({
    'alerts', 'delivered_alerts', 'events', 'fanouts', 'recipients', 'delivered_recipients'})
_EVENTS_FOR_ALERT = ("SELECT coalesce(jsonb_agg(seq::text ORDER BY seq),'[]'::jsonb) "
    "FROM sentinel_alert_delivery_events WHERE alert_id='{}'")
_CURRENT_ACQUISITION = ("SELECT json_build_object('holder',holder_id,'generation',control_generation,"
    "'fence',fence_token,'acquired',acquired_at) FROM sentinel_automation_lease WHERE id=1")
_HEALTH_EPISODE = 'SELECT active_identity FROM sentinel_alert_health_cursor WHERE id=1'


def require_qualified_same_tool(host):
    """An old installed release cannot borrow this newer acceptance rule."""
    runtime_root = Path(__file__).resolve().parents[2]
    selected_root = Path(host.request['source']).resolve()
    require(runtime_root == selected_root, 'REACTIVATED_STARTUP_HOST_NOT_CANDIDATE')
    files = list((runtime_root/'scripts/sentinel_local_delivery').rglob('*.py'))
    files.append(runtime_root/'scripts/sentinel_backed_local_patch.py')
    recorded = host.request['qualification']['source_files']
    require(files and isinstance(recorded, dict), 'REACTIVATED_STARTUP_HOST_NOT_QUALIFIED')
    for path in files:
        name = path.relative_to(runtime_root).as_posix()
        require(recorded.get(name) == hashlib.sha256(path.read_bytes()).hexdigest(),
                'REACTIVATED_STARTUP_HOST_NOT_QUALIFIED')


def _alert_id(preserved, current):
    """Classify only the shape of a possible append; this is not its witness."""
    before = preserved.get('retained_incidents')
    after = current.get('retained_incidents') if isinstance(current, dict) else None
    require(isinstance(before, dict) and isinstance(after, dict),
            'REACTIVATED_STARTUP_INCIDENT_CHANGED')
    if after == before:
        require(current == preserved, 'REACTIVATED_STARTUP_PRESERVED_STATE_CHANGED')
        return None
    added = set(after) - set(before)
    require(len(added) == 1, 'REACTIVATED_STARTUP_INCIDENT_CHANGED')
    alert_id = next(iter(added))
    require(isinstance(alert_id, str) and re.fullmatch('[0-9a-f]{64}', alert_id),
            'REACTIVATED_STARTUP_INCIDENT_CHANGED')
    changed_reactivation = current.get('reactivation')
    previous_reactivation = preserved.get('reactivation')
    if (isinstance(changed_reactivation, dict) and isinstance(previous_reactivation, dict)
            and changed_reactivation.get('unsettled_alerts') == 1
            and changed_reactivation == dict(previous_reactivation, unsettled_alerts=1)):
        # This comparison only identifies a pending candidate. No replacement
        # state is returned or admitted to a financial/preservation check.
        require(set(current) == set(preserved)
                and all(current[key] == value for key, value in preserved.items()
                        if key not in {'retained_incidents', 'reactivation'})
                and all(after.get(key) == value for key, value in before.items()),
                'REACTIVATED_STARTUP_PRESERVED_STATE_CHANGED')
        alert = after[alert_id]
        payload = alert.get('payload') if isinstance(alert, dict) else None
        require(isinstance(alert, dict)
                and alert.get('event_type') == 'AUTOMATION_OPERATIONAL_RED'
                and alert.get('severity') == 'CRITICAL'
                and alert.get('ack_state') == 'UNACKNOWLEDGED'
                and isinstance(payload, dict)
                and payload.get('reason') == 'WAITING_FOR_LEADER'
                and payload.get('control_generation') == preserved['control']['generation']
                and type(payload.get('broker_outcome_unresolved')) is int
                and payload['broker_outcome_unresolved'] == 0,
                'REACTIVATED_STARTUP_INCIDENT_CHANGED')
        raise DeliveryRefused('REACTIVATED_STARTUP_ALERT_PENDING')
    evidence.reactivated_observed_state(preserved, current, alert_id)
    return alert_id


def _tentative_notification_append(host, prior, alert_id):
    """Prior notification rows are exact; new rows must belong to this alert."""
    current = evidence.notification_history(host)
    require(isinstance(prior, dict) and set(prior) == set(current) == _HISTORY_GROUPS
            and all(isinstance(prior[group], dict) for group in _HISTORY_GROUPS),
            'REACTIVATED_STARTUP_NOTIFICATION_CHANGED')
    added = {}
    for group in _HISTORY_GROUPS:
        old, now = prior[group], current[group]
        require(all(now.get(key) == value for key, value in old.items()),
                'REACTIVATED_STARTUP_NOTIFICATION_CHANGED')
        added[group] = set(now) - set(old)
    require(added['alerts'] == {alert_id}
            and added['delivered_alerts'] <= {alert_id}
            and added['fanouts'] <= {alert_id}
            and all(key.startswith(alert_id + ':') for group in ('recipients', 'delivered_recipients')
                    for key in added[group]), 'REACTIVATED_STARTUP_NOTIFICATION_CHANGED')
    events = host.sql(_EVENTS_FOR_ALERT.format(alert_id))
    require(isinstance(events, list) and all(isinstance(seq, str) and seq.isdigit()
            for seq in events) and added['events'] == set(events),
            'REACTIVATED_STARTUP_NOTIFICATION_CHANGED')
    require(evidence.notification_history(host) == current,
            'REACTIVATED_STARTUP_NOTIFICATION_CHANGED')


def tentative_startup(host, receipt, applications, hashes):
    """Admit a process milestone with one *unclassified* startup incident."""
    artifacts = receipt['artifacts']
    require(host.candidate_apps_ready(hashes, applications), 'APPLICATION_CONFIGURATION_CHANGED')
    current = host.sql(checks.snapshot_sql('POST_TRADE_REACTIVATED'))
    alert_id = _alert_id(artifacts['preserved'], current)
    require(alert_id is not None, 'REACTIVATED_STARTUP_INCIDENT_CHANGED')
    require_qualified_same_tool(host)
    for service in SERVICES:
        item = applications[service]
        require(isinstance(item.get('Id'), str) and re.fullmatch('[0-9a-f]{64}', item['Id'])
                and item.get('RestartCount') == 0
                and datetime.fromisoformat(item['State']['StartedAt']).utcoffset() is not None,
                'APPLICATION_STARTUP_PROCESS_CHANGED')
    # A full financial/source snapshot must accept the sole alert's shape and
    # every other preflight fact, even though no incident cause is accepted yet.
    checked = evidence.snapshot(host, startup_alert_id=alert_id)
    require(checked == current, 'REACTIVATED_STARTUP_OBSERVATION_CHANGED')
    _tentative_notification_append(host, artifacts['notification_history'], alert_id)
    return dict(startup_alert_id=alert_id, observed_state=current), dict(
        alert_id=alert_id, alert_sha256=digest(current['retained_incidents'][alert_id]))


def wait_for_startup_recovery(host, receipt, leader, applications, *, deadline, clock, sleep, end):
    """Wait for the original health episode to clear under the original cutoff."""
    current = host.sql(_CURRENT_ACQUISITION)
    require(isinstance(current, dict)
            and all(current.get(key) == leader.get(key) for key in ('holder', 'generation', 'fence')),
            'REACTIVATED_STARTUP_LEADER_CHANGED')
    acquired = datetime.fromisoformat(current['acquired'])
    started = datetime.fromisoformat(applications['sentinel-automation']['State']['StartedAt'])
    require(acquired.utcoffset() is not None and started.utcoffset() is not None
            and started <= acquired <= started + timedelta(seconds=30),
            'REACTIVATED_STARTUP_ACQUISITION_CHANGED')
    subject = None
    while True:
        observed = host.sql(checks.snapshot_sql('POST_TRADE_REACTIVATED'))
        alert_id = _alert_id(receipt['artifacts']['preserved'], observed)
        require(alert_id is not None, 'REACTIVATED_STARTUP_INCIDENT_CHANGED')
        candidate = (alert_id, digest(observed['retained_incidents'][alert_id]))
        require(subject is None or candidate == subject, 'REACTIVATED_STARTUP_INCIDENT_CHANGED')
        subject = candidate
        latest = evidence.leader(host)
        require(latest['current'] and all(latest[key] == leader[key]
                for key in ('holder', 'generation', 'fence')),
                'REACTIVATED_STARTUP_LEADER_CHANGED')
        episode = host.sql(_HEALTH_EPISODE)
        if episode is None:
            return
        require(isinstance(episode, str), 'REACTIVATED_STARTUP_HEALTH_EPISODE_CHANGED')
        try:
            value = json.loads(episode)
            identity = value['identity']
            recovery = value['recovery']
        except (ValueError, TypeError, KeyError) as exc:
            raise DeliveryRefused('REACTIVATED_STARTUP_HEALTH_EPISODE_CHANGED') from exc
        require(identity == ['LEADERSHIP', leader['generation'], 0]
                and (recovery is None or (recovery.get('holder') == leader['holder']
                    and recovery.get('fence') == leader['fence'])),
                'REACTIVATED_STARTUP_HEALTH_EPISODE_CHANGED')
        remaining = min((end - utcnow()).total_seconds(), deadline - clock())
        require(remaining > 0, 'APPLICATION_READINESS_DEADLINE')
        sleep(min(3, remaining))


def observed_startup(host, receipt, *, tentative=None):
    """Prove an append with the shared positive witness on the qualified host."""
    preserved = receipt['artifacts']['preserved']
    current = host.sql(checks.snapshot_sql('POST_TRADE_REACTIVATED'))
    alert_id = _alert_id(preserved, current)
    if tentative is not None:
        require(alert_id == tentative['alert_id'] and
                digest(current['retained_incidents'][alert_id]) == tentative['alert_sha256'],
                'REACTIVATED_STARTUP_INCIDENT_CHANGED')
    if alert_id is None:
        return preserved, None
    require_qualified_same_tool(host)
    witness = reactivated_startup.observe_startup_append(host, receipt, current)
    require(witness['alert_id'] == alert_id
            and witness['alert_sha256'] == digest(current['retained_incidents'][alert_id]),
            'REACTIVATED_STARTUP_WITNESS_CHANGED')
    observed = evidence.snapshot(host, startup_alert_id=alert_id)
    require(observed == current, 'REACTIVATED_STARTUP_OBSERVATION_CHANGED')
    return evidence.reactivated_observed_state(preserved, observed, alert_id), witness


def final_notification_append(host, receipt, witness):
    alert_id = witness['alert_id']
    _tentative_notification_append(host, receipt['artifacts']['notification_history'], alert_id)
    history = evidence.notification_history(host)
    prior = receipt['artifacts']['notification_history']
    require(set(history['events']) - set(prior['events']) ==
            {str(witness['claim_seq']), str(witness['delivery_seq'])}
            and set(history['delivered_alerts']) - set(prior['delivered_alerts']) == {alert_id},
            'REACTIVATED_STARTUP_NOTIFICATION_CHANGED')
