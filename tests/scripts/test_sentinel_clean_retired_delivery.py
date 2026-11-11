"""A clean skip can admit software without admitting a retired order."""
from copy import deepcopy
from dataclasses import replace
import datetime as datetime_module
from datetime import datetime

import pytest

from tests.scripts.test_sentinel_backed_local_patch import settled_host, fixture
from tests.scripts.test_sentinel_posttrade_postgres import conn, pg, cycle, admitted

checks = fixture.checks


def retired_host():
    host = settled_host()
    host.state['cycle'].update(state='SUPERSEDED', failure_code=checks.CASH_RETIRED_REASON,
        failure_detail=checks.CASH_RETIRED_DETAIL, diagnostic=dict(clean=True,
            runtime_state='RUNNING', cash_plan_superseded=True, observation_id=247,
            unresolved=[], foreign_orders=[], foreign_positions=[], restricted_securities={}))
    host.state['retired_plan_commands'] = 0
    return host


def test_install_preserves_literal_terminal_state_and_original_plan():
    host = retired_host()
    before = deepcopy(host.state)
    assert fixture.evidence.snapshot(host) == before
    assert host.state == before
    assert host.calls == [checks.snapshot_sql('POST_TRADE')]
    assert before['cycle']['state'] == 'SUPERSEDED'


@pytest.mark.parametrize('key,value', [
    ('clean', False), ('clean', 'true'), ('runtime_state', 'RECONCILING'),
    ('cash_plan_superseded', False), ('observation_id', 248), ('observation_id', None),
    ('unresolved', ['unknown']), ('foreign_orders', ['order']),
    ('foreign_positions', ['position']), ('restricted_securities', {'asset': 'restricted'}),
])
def test_negative_or_mismatched_diagnostic_never_admits_install(key, value):
    host = retired_host()
    host.state['cycle']['diagnostic'][key] = value
    with pytest.raises(fixture.model.DeliveryRefused):
        fixture.evidence.snapshot(host)


@pytest.mark.parametrize('key,value', [
    ('failure_code', 'HISTORICAL_OBLIGATIONS_RECOVERED'), ('failure_detail', 'other'),
    ('completed_at', None), ('state', 'RECONCILING'), ('last_clean_reconciliation_id', '248'),
])
def test_other_terminal_outcomes_do_not_inherit_skip_admission(key, value):
    host = retired_host()
    host.state['cycle'][key] = value
    with pytest.raises(fixture.model.DeliveryRefused):
        fixture.evidence.snapshot(host)


@pytest.mark.parametrize('commands', [1, None, False, '0'])
def test_even_a_terminal_command_for_the_skipped_plan_refuses(commands):
    host = retired_host()
    host.state['retired_plan_commands'] = commands
    with pytest.raises(fixture.model.DeliveryRefused, match='RETIRED_PLAN_COMMANDS_EXIST'):
        fixture.evidence.snapshot(host)


def test_removing_zero_command_guard_has_an_executed_falsifier(monkeypatch):
    original = fixture.evidence.require
    monkeypatch.setattr(fixture.evidence, 'require', lambda ok, reason:
        None if reason == 'RETIRED_PLAN_COMMANDS_EXIST' else original(ok, reason))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_even_a_terminal_command_for_the_skipped_plan_refuses(1)


def install_retired_sql_row(conn):
    cycle(conn)
    conn.execute("UPDATE handoff_cycle SET state='SUPERSEDED',failure_code=%s,failure_detail=%s,"
        "diagnostic=%s::jsonb", (checks.CASH_RETIRED_REASON, checks.CASH_RETIRED_DETAIL,
        __import__('json').dumps(retired_host().state['cycle']['diagnostic'])))


@pytest.mark.parametrize('mutation', [
    "diagnostic=diagnostic-'clean'", "diagnostic=diagnostic-'cash_plan_superseded'",
    "diagnostic=jsonb_set(diagnostic,'{observation_id}','248')",
    "diagnostic=jsonb_set(diagnostic,'{unresolved}','[\"UNKNOWN\"]')",
    "diagnostic=jsonb_set(diagnostic,'{foreign_orders}','[\"foreign\"]')",
    "failure_code='OTHER'", "completed_at=NULL", "historical_state_only=true",
])
def test_database_filter_refuses_negative_skip_facts(conn, mutation):
    install_retired_sql_row(conn)
    assert admitted(conn) is True
    conn.execute('UPDATE handoff_cycle SET '+mutation)
    assert admitted(conn) is not True


def test_successor_mode_does_not_gain_clean_skip_exception(conn):
    install_retired_sql_row(conn)
    candidate, ready = checks.handoff_filters('POST_TRADE_SUCCESSOR')
    assert conn.execute('SELECT ('+candidate+') AND ('+ready+') FROM handoff_cycle s').fetchone()[0] is not True


def skipped_page(monkeypatch):
    from tests.scripts import test_install_unified_readiness as unified
    from tests.sentinel import test_opening_health_continuity as opening
    from sentinel.panel import operational_snapshot
    from sentinel.panel.serialization import public_payload

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return opening.NOW.replace(tzinfo=None) if tz is None else opening.NOW.astimezone(tz)

    # The embedded validators import datetime when they run. Keep their
    # freshness checks and the readiness harness on the fixture's dated clock.
    monkeypatch.setattr(datetime_module, 'datetime', Clock)
    monkeypatch.setattr(unified, 'datetime', Clock)
    panel = opening.clean_skip_panel()
    panel = replace(panel, rows=[replace(row, value='2026-11-09 · 0 sessions behind')
        if row.key=='feed' else replace(row, value='SHADOW VERIFIED THROUGH 2026-11-09')
        if row.key=='shadow_verification' else row for row in panel.rows])
    panel = replace(panel, observation_valid_until=operational_snapshot.original_boundary(panel))
    expected=dict(handoff_mode='POST_TRADE', clean_retired=True, plan='opening-plan',
        cycle_id='opening-cycle', decision='2026-11-09', effective='2026-11-10',
        completed_at=panel.row('trading_run').trading_run.updated_at.isoformat(), reconciliation_id=396)
    return public_payload(panel), expected


def test_strict_installer_accepts_actual_current_clean_skip_without_claiming_success(monkeypatch):
    from tests.scripts.test_sentinel_local_delivery_operator_review import execute_reader
    page, expected = skipped_page(monkeypatch)
    before=deepcopy(page)
    result=execute_reader(monkeypatch, page, expected, code=checks.SKIPPED_PANEL)
    assert result['terminal_state']=='SUPERSEDED' and result['reconciliation_id']==396
    assert result['terminal_reason']==checks.CASH_RETIRED_REASON
    assert result['installation_scope']=='CLEAN_RETIRED_PLAN_COMPATIBLE_APPLICATION_REPAIR'
    assert page==before


@pytest.mark.parametrize('fault', ['wrong_plan','wrong_cycle','wrong_observation','expired','unknown',
    'not_current','source_error','false_success','command','active_condition'])
def test_strict_installer_refuses_false_skip_or_unknown_evidence(monkeypatch, fault):
    from tests.scripts.test_sentinel_local_delivery_operator_review import execute_reader, keyed
    page, expected=skipped_page(monkeypatch)
    paper=keyed(page,'paper_reconciliation')
    if fault=='wrong_plan':paper['operational_fact']['opening']['plan_id']='foreign'
    elif fault=='wrong_cycle':paper['operational_fact']['opening']['cycle_id']='foreign'
    elif fault=='wrong_observation':paper['operational_fact']['opening']['observation_id']=397
    elif fault=='expired':paper['valid_until']=expected['completed_at']
    elif fault=='unknown':keyed(page,'authority')['status']='unknown'
    elif fault=='not_current':page['observation']['strict_current']=False
    elif fault=='source_error':page['source_errors']=['unavailable']
    elif fault=='false_success':keyed(page,'trading_run')['trading_run']['state']='SUCCEEDED'
    elif fault=='command':keyed(page,'trading_run')['trading_run']['orders']=[{'state':'UNKNOWN'}]
    else:page['dashboard_health']['active_conditions']=['broker']
    with pytest.raises((AssertionError, ValueError)):
        execute_reader(monkeypatch, page, expected, code=checks.SKIPPED_PANEL)


def test_strict_observation_binding_guard_has_an_executed_falsifier(monkeypatch):
    needle="assert fact.opening.observation_id==int(expected['reconciliation_id'])"
    assert checks.SKIPPED_PANEL.count(needle)==1
    monkeypatch.setattr(checks, 'SKIPPED_PANEL', checks.SKIPPED_PANEL.replace(needle,''))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_strict_installer_refuses_false_skip_or_unknown_evidence(monkeypatch,'wrong_observation')
