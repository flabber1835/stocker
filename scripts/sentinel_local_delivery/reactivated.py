"""Read-only guard for a healthy direct successor after signed PAPER reactivation."""
from __future__ import annotations

import inspect
import re

from .model import require


SNAPSHOT_FACTS = """ 'reactivation',json_build_object(
    'events',(SELECT jsonb_agg(jsonb_build_object('generation',e.generation,'action',e.action,
         'seq',e.seq,'actor',e.actor,'reason',e.reason,'detail',e.detail) ORDER BY e.generation)
      FROM sentinel_automation_events e WHERE e.generation>s.control_generation AND e.generation<=c.generation),
    'unsettled_alerts',(SELECT count(*) FROM sentinel_alert_outbox WHERE severity='CRITICAL'
      AND ack_state='UNACKNOWLEDGED' AND (state<>'DELIVERED' OR delivered_at IS NULL)),
    'successor_commands',(SELECT count(*) FROM sentinel_commands x WHERE x.plan_id=p.plan_id)), """


def require_lineage(state, *, startup_alert_id=None):
    previous = state['cycle']['control_generation']
    current = state['control']['generation']
    proof = state.get('reactivation')
    require(isinstance(proof, dict) and current == previous + 4
            and all(type(proof.get(key)) is int and proof[key] == 0
                    for key in ('unsettled_alerts', 'successor_commands')),
            'REACTIVATED_HANDOFF_NOT_QUIESCENT')
    events = proof.get('events')
    actions = ['KILL_ENGAGED', 'DEACTIVATED', 'ACTIVATED', 'KILL_RELEASED']
    require(isinstance(events, list) and len(events) == len(actions)
            and all(isinstance(e, dict) and e.get('generation') == previous + i
                    and e.get('action') == action for i, (e, action) in enumerate(zip(events, actions), 1)),
            'REACTIVATED_CONTROL_LINEAGE_CHANGED')
    require(events[0].get('reason') == 'autonomous deploy fail-closed fence',
            'REACTIVATED_DEPLOYMENT_FENCE_REQUIRED')
    incidents = state.get('retained_incidents')
    require(isinstance(incidents, dict), 'REACTIVATED_INCIDENT_HISTORY_ABSENT')
    startup_seen = False
    for alert_id, alert in incidents.items():
        require(isinstance(alert_id, str) and re.fullmatch('[0-9a-f]{64}', alert_id)
                and isinstance(alert, dict) and alert.get('severity') == 'CRITICAL'
                and alert.get('ack_state') == 'UNACKNOWLEDGED' and isinstance(alert.get('payload'), dict),
                'REACTIVATED_INCIDENT_INVALID')
        payload = alert['payload']
        if alert_id == startup_alert_id:
            require(not startup_seen
                    and alert.get('event_type') == 'AUTOMATION_OPERATIONAL_RED'
                    and payload.get('reason') == 'WAITING_FOR_LEADER'
                    and payload.get('control_generation') == current
                    and type(payload.get('broker_outcome_unresolved')) is int
                    and payload['broker_outcome_unresolved'] == 0,
                    'REACTIVATED_STARTUP_ALERT_CHANGED')
            startup_seen = True
        elif alert.get('event_type') == 'AUTOMATION_KILL_ENGAGED':
            event = events[0]
            require(payload.get('control_event_seq') == event['seq']
                    and all(payload.get(k) == event[k] for k in ('generation', 'action', 'actor', 'reason', 'detail')),
                    'REACTIVATED_HISTORICAL_FENCE_CHANGED')
        else:
            require(alert.get('event_type') == 'AUTOMATION_OPERATIONAL_RED'
                    and payload.get('reason') == 'WAITING_FOR_LEADER'
                    and payload.get('control_generation') == previous
                    and type(payload.get('broker_outcome_unresolved')) is int
                    and payload['broker_outcome_unresolved'] == 0, 'REACTIVATED_UNRELATED_INCIDENT')
    if startup_alert_id is not None:
        require(startup_seen, 'REACTIVATED_STARTUP_ALERT_ABSENT')


def verified_panel(page, header, expected, now):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from sentinel.feed.calendar import next_session
    from sentinel.panel.review_model import OperatorReview

    def clock(raw):
        value = datetime.fromisoformat(raw)
        assert value.utcoffset() is not None
        return value

    rows = {row['key']: row for row in page['rows']}
    assert len(rows) == len(page['rows']) and not page['source_errors']
    observation = page['observation']
    health = page['dashboard_health']
    assert header == 'CURRENT' and observation['current'] is True and observation['strict_current'] is True
    assert observation['changed_scopes'] == observation['revalidated_keys'] == []
    observed = clock(page['as_of'])
    expires = min(clock(observation['valid_until']), clock(health['valid_until']))
    assert now - timedelta(seconds=120) <= observed <= now + timedelta(seconds=5)
    assert now < expires <= observed + timedelta(seconds=30)
    review = OperatorReview.model_validate(page['operator_review'])
    assert review.status in {'CLEAN', 'REVIEW'} and not review.active and not health['active_conditions']
    assert now - timedelta(seconds=120) <= review.observed_at <= now + timedelta(seconds=5)
    assert set(review.warnings) == set(health['review_conditions']) <= {'paper_reconciliation'}
    assert health['status'] in {'ok', 'warn'} and page['color'] in {'green', 'amber'}
    for key in ('authority', 'runtime_identity', 'broker', 'alpaca_account', 'backup_restore', 'book', 'exposure',
                'terminals', 'shadow_verification', 'shadow_nav', 'shadow_return', 'shadow_worker', 'feed',
                'alert_dispatcher', 'automation_leader', 'automation', 'completed_trading_run'):
        assert rows[key]['status'] == 'ok'
    assert rows['shadow_verification']['value'] == 'SHADOW VERIFIED THROUGH '+expected['decision']
    assert rows['feed']['value'] == expected['decision']+' · 0 sessions behind'
    assert rows['automation']['value'] == 'ENABLED · KILL RELEASED'
    assert now-timedelta(seconds=30) <= clock(rows['automation_leader']['as_of']) <= now+timedelta(seconds=5)
    assert now < clock(rows['automation_leader']['valid_until'])
    run = rows['completed_trading_run']['trading_run']
    intent = run['intent']
    assert run['state'] == 'SUCCEEDED' and clock(run['completed_at']) <= now
    assert intent['cycle_id'] == expected['cycle_id'] and intent['plan_id'] == expected['original_plan'] != expected['plan']
    assert intent['decision_session'] == expected['decision'] and intent['effective_session'] == expected['effective']
    plan = rows['paper_plan']
    assert plan['status'] == 'pending' and plan['paper_plan'] is None
    if plan['value'] != 'NOT PREPARED':
        assert intent['effective_session'] == observed.astimezone(ZoneInfo('America/New_York')).date().isoformat()
        assert plan['value'] == f"{next_session(intent['effective_session'])} · awaiting plan"
    recovery_values = {'automation_cycle':'WAITING FOR NEXT DECISION', 'automation_step_discovery':'WAITING FOR CYCLE'}
    for key, value in recovery_values.items():
        row = rows[key]
        recovery = row['recovery']
        assert row['value'] == value and row['status'] == 'warn' and row['required_current'] is True
        assert recovery['phase'] == 'AUTOMATION_DISCOVERY' and recovery['automatic'] is True
        assert recovery['operator_required'] is False and recovery['active'] is True and now < clock(recovery['deadline'])
    historical = rows['paper_reconciliation']
    if historical['status'] != 'ok' or review.warnings:
        assert historical['status'] == 'warn' and historical['paper_alignment'] == 'COMPLETED_WITH_HISTORY'
        assert historical['operational_fact']['kind'] == 'PAPER_VERIFICATION'
        assert historical['operational_fact']['state'] == 'PENDING' and now < clock(historical['valid_until'])
    pending = {'paper_plan', *('automation_step_'+k for k in ('data','prepare','open','transport','reconcile','complete'))}
    for row in rows.values():
        key, status = row['key'], row['status']
        assert status in {'ok','warn','pending'} and row['color'] == {'ok':'green','warn':'amber','pending':'amber'}[status]
        assert row['current'] is True and row['stale'] is False and row['future'] is False
        if row['required_current'] and row.get('valid_until'):
            assert now < clock(row['valid_until'])
        if status == 'pending':
            assert key in pending and row['required_current'] is False
        if status == 'warn':
            assert key in {'paper_reconciliation','automation_alerts', *recovery_values}
    alerts = rows['automation_alerts']
    count = len(expected['retained_incidents'])
    assert alerts['value'] == f'0 pending · 0 DLQ · {count} unacked'
    assert alerts['required_current'] is False and alerts['status'] == ('warn' if count else 'ok')
    return dict(as_of=page['as_of'], color=page['color'], operational_ready=False,
                completed_cycle=intent['cycle_id'], completed_plan=intent['plan_id'], current_plan=expected['plan'],
                installation_panel_valid_until=expires.isoformat(), source_errors=page['source_errors'])


PANEL_BODY = inspect.getsource(verified_panel) + """
from sentinel.feed import store
import os
conn=store.connect(os.environ['SENTINEL_DATABASE_URL'],connect_timeout=3,statement_timeout_ms=3000)
try:
    conn.execute('SET TRANSACTION READ ONLY')
    actual=conn.execute("SELECT coalesce(jsonb_object_agg(alert_id,jsonb_build_object("
        "'event_type',event_type,'severity',severity,'payload',payload,'ack_state',ack_state,'created_at',created_at)),"
        "'{}'::jsonb) FROM sentinel_alert_outbox WHERE severity='CRITICAL' AND ack_state='UNACKNOWLEDGED'").fetchone()[0]
    assert actual==expected['retained_incidents']
finally:
    conn.rollback()
    conn.close()
print(json.dumps(verified_panel(page,response.headers.get('X-Sentinel-Panel-Status'),expected,
    datetime.now(timezone.utc)),sort_keys=True))
"""
