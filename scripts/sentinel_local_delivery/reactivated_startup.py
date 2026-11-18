"""Positive read-only proof of a recovered first-acquisition gap in local delivery."""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
import re
import subprocess

from . import checks
from .host import SERVICES, application_healthy
from .model import DeliveryRefused, REACTIVATED_SCHEMA, digest, require

_CODE = 'REACTIVATED_STARTUP_APPEND_UNPROVED'
_WINDOW = timedelta(seconds=30)
_ROLES = ('sentinel-automation', 'sentinel-alert-dispatcher')
_DIAGNOSTIC_FIELDS = frozenset("""
    schema policy_state predicate sampled_at control_generation fence holder holder_present holder_matches
    leader_active service_heartbeat_fresh lease_heartbeat_at lease_expires_at instance_state
    instance_heartbeat_at heartbeat_age_seconds heartbeat_window_seconds callback_started_at
    callback_deadline_at callback_current scheduler_overdue read_elapsed_seconds
""".split())

# Re-read the producer payload, claim, delivery, lease, both service instances,
# cursor and immutable historical notification digests in one read-only snapshot.
_SQL = """
SELECT jsonb_build_object(
 'alert',jsonb_build_object('event_type',a.event_type,'severity',a.severity,'payload',a.payload,
     'ack_state',a.ack_state,'created_at',a.created_at),
 'key',a.idempotency_key,'schema',a.schema_version,'state',a.state,'attempts',a.attempt_count,
 'delivered_at',a.delivered_at,'ack_empty',
     a.acknowledged_at IS NULL AND a.acknowledged_by IS NULL AND a.acknowledgement IS NULL,
 'events',(SELECT jsonb_agg(to_jsonb(e) ORDER BY e.seq) FROM sentinel_alert_delivery_events e
     WHERE e.alert_id=a.alert_id),
 'generation',c.generation,'enabled',c.enabled,'killed',c.kill_switch_engaged,'authority',c.authority_verdict,
 'lease_generation',l.control_generation,'holder',l.holder_id,'fence',l.fence_token,
 'acquired',l.acquired_at,'heartbeat',l.heartbeat_at,'expires',l.expires_at,
 'registered',s.started_at,'service_heartbeat',s.heartbeat_at,'service_state',s.state,
 'candidate_workers',(SELECT count(*) FROM sentinel_automation_service_instances
     WHERE instance_id LIKE 'sentinel-@SHORT@-%'),
 'previous_holder',old.instance_id,'previous_registered',old.started_at,
 'previous_heartbeat',old.heartbeat_at,'previous_state',old.state,
 'occurrence',h.occurrence,'cleared',h.active_identity IS NULL,'now',clock_timestamp(),
 'history',(@NOTIFICATIONS@))
FROM sentinel_alert_outbox a CROSS JOIN sentinel_automation_control c
JOIN sentinel_automation_lease l ON l.id=c.id
JOIN sentinel_automation_service_instances s ON s.instance_id=l.holder_id
CROSS JOIN sentinel_alert_health_cursor h
JOIN sentinel_automation_service_instances old ON old.instance_id=
 (SELECT x.payload#>>'{scheduler_diagnostic,holder}' FROM sentinel_alert_outbox x WHERE x.alert_id='@ID@')
WHERE a.alert_id='@ID@' AND c.id=1 AND h.id=1
""".replace('@NOTIFICATIONS@', checks.NOTIFICATION_SQL.strip())


def _clock(raw):
    value = datetime.fromisoformat(raw)
    require(value.utcoffset() == timedelta(0), _CODE)
    return value


def _check(condition):
    require(condition, _CODE)


def _same(left, right):
    # JSON canonicalization preserves types: false is not an integer zero.
    return digest(left) == digest(right)


def _notification_history(before, after, alert_id, events):
    groups = {'alerts', 'delivered_alerts', 'events', 'fanouts', 'recipients', 'delivered_recipients'}
    _check(set(before) == set(after) == groups)
    for group in groups:
        original, observed = before[group], after[group]
        _check(all(observed.get(k) == v for k, v in original.items()))
        appended = set(observed) - set(original)
        if group == 'events':
            _check(appended == {str(e['seq']) for e in events})
        elif group in {'recipients', 'delivered_recipients'}:
            _check(all(key.startswith(alert_id+':') for key in appended))
        elif group in {'alerts', 'delivered_alerts'}:
            _check(appended == {alert_id})
        else:
            _check(appended <= {alert_id})


def _validate(subject, facts, holder_file, diagnostic_log):
    alert_id, alert, process, stages, generation, history = subject
    payload = alert['payload']
    diagnostic = payload['scheduler_diagnostic']
    _check(set(diagnostic)==_DIAGNOSTIC_FIELDS)
    _check(_same(facts['alert'], alert) and set(alert) ==
           {'event_type', 'severity', 'payload', 'ack_state', 'created_at'})
    _check((alert['event_type'], alert['severity'], alert['ack_state']) ==
           ('AUTOMATION_OPERATIONAL_RED', 'CRITICAL', 'UNACKNOWLEDGED'))
    _check(set(payload) == {'reason','control_generation','broker_outcome_unresolved',
                            'latest_cycle_id','latest_cycle_state','scheduler_diagnostic'})
    _check(_same([payload['reason'],payload['control_generation'],payload['broker_outcome_unresolved'],
                  payload['latest_cycle_id'],payload['latest_cycle_state']],
                 ['WAITING_FOR_LEADER',generation,0,None,None]))
    _check(_same([facts['schema'],facts['state'],facts['attempts'],facts['ack_empty'],
                  facts['cleared'],facts['generation'],facts['lease_generation'],facts['enabled'],
                  facts['killed'],facts['authority'],facts['candidate_workers']],
                 [1,'DELIVERED',1,True,True,generation,generation,True,False,'PASS',1]))
    occurrence = facts['occurrence']
    _check(type(occurrence) is int and occurrence > 0 and
           facts['key'] == f'automation-health-occurrence:{occurrence}')
    _check(alert_id == hashlib.sha256(('sentinel.alert/1\0'+facts['key']).encode()).hexdigest())
    automation, dispatcher = (process[key] for key in _ROLES)
    short = automation['Id'][:12]
    _check(holder_file == facts['holder'] and re.fullmatch(
        'sentinel-'+short+'-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', holder_file))
    started, sender_started = (_clock(item['State']['StartedAt']) for item in (automation, dispatcher))
    stop, stopped, requested, recorded = (stages[key] for key in
        ('STOP_REQUESTED','APPLICATIONS_STOPPED','START_REQUESTED','APPLICATIONS_STARTED'))
    registered, sampled, created, acquired, delivered, now = map(_clock, (
        facts['registered'], diagnostic['sampled_at'], alert['created_at'], facts['acquired'],
        facts['delivered_at'], facts['now']))
    _check(stop < stopped < requested <= min(started,sender_started)
           <= max(started,sender_started) <= recorded)
    _check(started <= registered <= sampled and sender_started <= sampled
           and sampled <= created < acquired <= started + _WINDOW
           and created <= delivered <= started + _WINDOW)
    _check(_clock(facts['previous_registered']) < stop and
           _clock(facts['previous_heartbeat']) <= stopped and
           stop < _clock(diagnostic['lease_expires_at']) <= requested)
    _check(_same([diagnostic['schema'],diagnostic['policy_state'],diagnostic['predicate'],
                  diagnostic['control_generation'],diagnostic['holder_present'],diagnostic['holder_matches'],
                  diagnostic['leader_active'],diagnostic['service_heartbeat_fresh'],diagnostic['callback_current'],
                  diagnostic['scheduler_overdue'],diagnostic['callback_started_at'],diagnostic['callback_deadline_at']],
                 ['sentinel.scheduler-diagnostic/1','WAITING_FOR_LEADER','LEASE_EXPIRED',
                  generation,True,True,False,False,False,False,None,None]))
    _check(diagnostic['holder'] == facts['previous_holder'] != holder_file and
           diagnostic['instance_state'] == facts['previous_state'] == 'WAITING' and
           _clock(diagnostic['lease_heartbeat_at']) == _clock(diagnostic['instance_heartbeat_at'])
           == _clock(facts['previous_heartbeat']) < _clock(diagnostic['lease_expires_at']))
    age, window, elapsed = (diagnostic[k] for k in
        ('heartbeat_age_seconds','heartbeat_window_seconds','read_elapsed_seconds'))
    _check(all(type(v) in (int,float) and math.isfinite(v) for v in (age,window,elapsed)))
    old_pulse = _clock(facts['previous_heartbeat'])
    _check(1 <= window < age and 0 <= elapsed < _WINDOW.total_seconds()
           and abs(age-(sampled-old_pulse).total_seconds()) < .001
           and old_pulse + timedelta(seconds=window)==_clock(diagnostic['lease_expires_at']))
    _check(type(facts['fence']) is int and type(diagnostic['fence']) is int and
           facts['fence'] == diagnostic['fence']+1 and diagnostic['fence'] > 0)
    # A real expiry/reacquisition after this first acquisition necessarily advances the fence.
    pulse = _clock(facts['heartbeat'])
    _check(facts['service_state'] == 'WAITING' and acquired < pulse <= now < _clock(facts['expires'])
           and _clock(facts['service_heartbeat']) == pulse and acquired + timedelta(seconds=60) <= now)
    _check(len(diagnostic_log) == 1)
    stamp, logged = diagnostic_log[0]
    _check(sampled <= _clock(stamp) <= created and _same(diagnostic, logged))
    events = facts['events']
    _check(isinstance(events,list) and len(events)==2 and
           [e['action'] for e in events] == ['CLAIMED','DELIVERED'])
    claim, done = events
    _check(all(e['alert_id']==alert_id and type(e['attempt']) is int and e['attempt']==1
               and e['error'] is None and type(e['seq']) is int for e in events))
    _check(claim['seq'] < done['seq'] and claim['holder_id'] and claim['holder_id']==done['holder_id']
           and created <= _clock(claim['at']) <= delivered <= _clock(done['at']) <= started + _WINDOW)
    _notification_history(history, facts['history'], alert_id, events)
    return dict(schema='sentinel.reactivated-startup-append/1', alert_id=alert_id, alert_sha256=digest(alert),
                diagnostic_sha256=digest(diagnostic), automation_container=automation['Id'],
                dispatcher_container=dispatcher['Id'], generation=generation, fence=facts['fence'],
                occurrence=occurrence, first_acquired_at=facts['acquired'], delivered_at=facts['delivered_at'],
                claim_seq=claim['seq'], delivery_seq=done['seq'])


def observe_startup_append(host, receipt, current):
    """Require the exact bounded pre-acquisition occurrence and continuing recovery."""
    try:
        _check(receipt['schema']==REACTIVATED_SCHEMA and receipt['stage']=='APPLICATIONS_STARTED'
               and host.request['schema']==REACTIVATED_SCHEMA
               and host.request['handoff_mode']=='POST_TRADE_REACTIVATED'
               and receipt['request_sha256']==digest(host.request))
        artifacts = receipt['artifacts']
        before = artifacts['preserved']
        original = before['retained_incidents']
        incidents = current['retained_incidents']
        _check(isinstance(incidents,dict) and isinstance(original,dict) and
               _same({**current,'retained_incidents':original},before) and
               all(key in incidents and _same(incidents[key],value) for key,value in original.items()))
        added = set(incidents)-set(original)
        _check(len(added)==1)
        alert_id = added.pop()
        _check(isinstance(alert_id,str) and re.fullmatch('[0-9a-f]{64}',alert_id))
        _check(_same([current['inflight'],current['other_active'],current['reactivation']['unsettled_alerts'],
                      current['reactivation']['successor_commands']], [0,0,0,0]))
        generation = current['control']['generation']
        _check(type(generation) is int and generation>0)
        process = artifacts['started_applications']
        _check(set(process)==set(SERVICES))
        apps = host.containers(SERVICES)
        for role in SERVICES:
            item, saved = apps[role], process[role]
            _check(application_healthy(item,host.request['candidate']['image'])
                   and re.fullmatch('[0-9a-f]{64}',saved['Id']) and saved['Id']==item['Id']
                   and _same([item['RestartCount'],saved['RestartCount']], [0,0])
                   and item['State']['StartedAt']==saved['State']['StartedAt'])
        auto_id, sender_id = (process[role]['Id'] for role in _ROLES)
        facts = host.sql(_SQL.replace('@ID@',alert_id).replace('@SHORT@',auto_id[:12]))
        holder = host.run(['docker','exec',auto_id,'cat','/tmp/sentinel-automation-holder-id'],
                          timeout=5).stdout.decode('ascii').strip()
        started = _clock(process[_ROLES[1]]['State']['StartedAt'])
        result = host.run(['docker','logs','--timestamps','--tail','100','--since',started.isoformat(),
                           '--until',(started+_WINDOW).isoformat(),sender_id],timeout=5)
        raw = result.stdout+b'\n'+result.stderr
        _check(len(raw)<=256*1024)
        logged = []
        for line in raw.decode().splitlines():
            stamp, _, body = line.partition(' ')
            if not body.startswith('{'):
                continue
            message = json.loads(body)
            if message.get('schema')=='sentinel.scheduler-incident/1':
                logged.append((stamp,message['diagnostic']))
        stages = {e['stage']:_clock(e['at']) for e in receipt['history']}
        subject = (alert_id,incidents[alert_id],process,stages,generation,artifacts['notification_history'])
        return _validate(subject,facts,holder,logged)
    except (KeyError,IndexError,TypeError,ValueError,OverflowError,AttributeError,OSError,subprocess.TimeoutExpired) as exc:
        raise DeliveryRefused(_CODE) from exc
