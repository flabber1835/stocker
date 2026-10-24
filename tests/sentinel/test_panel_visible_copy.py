from datetime import date, datetime, timedelta, timezone

import pytest

from sentinel.operational_status import RecoveryEvidence
from sentinel.panel import model
from sentinel.panel.presentation import describe
from sentinel.panel.styles import CSS
from sentinel.panel.render import _row_html
from sentinel.paper_plan_preview import PlanPreview


NOW = datetime(2026, 10, 22, 22, tzinfo=timezone.utc)


def test_scheduled_wait_and_unavailable_copy_preserve_raw_evidence_and_verdict():
    for value, display, status in (
            ('WAITING_OPEN', 'Waiting for market open', model.WARN),
            ('UNKNOWN', 'Status unavailable', model.UNKNOWN)):
        row = model.Row('automation_cycle', 'Cycle', value, status,
                        'original reason <recorded>')
        label, shown, explanation = describe(row, status)
        assert label == 'Current daily run' and shown == display
        html = _row_html(row, NOW)
        assert f'data-status="{status}"' in html
        assert f'<div class="value">{display}</div>' in html
        assert f'Cycle · {value}<br>original reason &lt;recorded&gt;' in html
        assert row.value == value and row.status == status
    uncertain = model.Row('broker', 'Broker', 'UNKNOWN OUTCOME', model.UNKNOWN)
    assert describe(uncertain, model.UNKNOWN)[1] == 'UNKNOWN OUTCOME'


@pytest.mark.parametrize('execute_at, expected', [
    (datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc),
     '2026-10-23 at 06:30 AM Pacific'),
    (datetime(2026, 11, 6, 14, 30, tzinfo=timezone.utc),
     '2026-11-06 at 06:30 AM Pacific'),
])
def test_saved_plan_schedule_is_visible_in_pacific_time_without_expansion(execute_at, expected):
    plan = PlanPreview(cycle_id='cycle', plan_id='plan',
        decision_session=date(2026, 10, 22), effective_session=execute_at.date(),
        execute_at=execute_at, created_at=NOW, observation_at=NOW, legs=[])
    row = model.Row('paper_plan', 'Next paper plan', '0 buys · 0 sells', model.OK,
                    'saved evidence', paper_plan=plan)
    html = _row_html(row, NOW)
    visible = html.split('<details', 1)[0]
    assert 'Saved execution: '+expected+'.' in visible
    assert row.paper_plan == plan and row.status == model.OK


def test_wait_copy_does_not_guess_a_schedule_from_freeform_details():
    row = model.Row('automation_cycle', 'Cycle', 'WAITING_OPEN', model.WARN,
                    'scheduled 2026-10-23 13:30Z; next wake 2026-10-22 22:01Z')
    _, _, explanation = describe(row, model.WARN)
    assert 'Saved execution:' not in explanation and 'Pacific' not in explanation
    assert '2026-10-23' not in explanation


def test_known_day_order_wait_and_expiry_keep_their_existing_severity():
    row = model.Row('automation_step_transport', 'Order transport',
        'DAY ORDERS WORKING', model.WARN, 'matched command evidence', NOW,
        required_current=True, recovery=RecoveryEvidence(
            phase='PROTECTED_DAY_ORDER_OBSERVATION', automatic=True,
            deadline=NOW+timedelta(minutes=1)))
    current = _row_html(row, NOW)
    assert 'data-status="warn"' in current
    assert 'Known DAY orders remain open' in current
    assert 'target completion is not yet confirmed' in current
    expired = _row_html(row, NOW+timedelta(minutes=2))
    assert 'data-status="fail"' in expired
    assert 'working-order evidence is no longer current' in expired
    assert 'Known DAY orders remain open' not in expired
    assert 'Order transport · DAY ORDERS WORKING<br>matched command evidence' in expired


def test_missed_buy_submission_is_explicit_and_stays_failed():
    row = model.Row('automation_step_transport', 'Order transport',
        'MISSED UNSENT BUYs', model.FAIL, 'cutoff expired with unsent deltas')
    html = _row_html(row, NOW)
    assert 'data-status="fail"' in html
    assert '<div class="value">Buy submission window expired</div>' in html
    assert 'not submitted before the original cutoff' in html
    assert 'Existing broker orders still require reconciliation' in html
    assert 'Order transport · MISSED UNSENT BUYs<br>cutoff expired with unsent deltas' in html


def test_source_wait_copy_requires_structured_phase_and_never_claims_verification():
    row = model.Row('shadow_verification', 'Shadow verification',
        'WAITING FOR INPUTS · owed 2026-10-22', model.WARN,
        'SOURCE_FRONTIER text alone is not structured evidence', NOW,
        required_current=True, recovery=RecoveryEvidence(
            phase='SOURCE_FRONTIER', automatic=True,
            deadline=NOW+timedelta(minutes=1)))
    html = _row_html(row, NOW)
    assert 'data-status="warn"' in html
    assert 'Market data for the next decision is still pending' in html
    assert 'Current-session verification must wait' in html
    assert 'keep their original attestation date' in html
    assert 'This result is unverified' in html
    expired = _row_html(row, NOW+timedelta(minutes=2))
    assert 'data-status="fail"' in expired and 'Attention needed' in expired
    assert 'Market data for the next decision is still pending' not in expired
    spoof = model.Row('shadow_verification', 'Shadow verification', row.value,
                     model.WARN, row.detail)
    assert 'Market data for the next decision is still pending' not in describe(spoof, model.WARN)[2]


def test_current_styles_keep_narrow_screen_values_and_accessibility_without_decoration():
    assert '@media(max-width:360px){body{font-size:14px}.row{padding:12px}.value{font-size:16px}}' in CSS
    assert 'prefers-reduced-motion:reduce' in CSS and 'animation:none!important' in CSS
    assert 'summary:focus-visible,a:focus-visible' in CSS
    assert 'repeat(2,minmax(0,1fr))' in CSS
    assert all(name not in CSS for name in ('casino-stage', 'casino-accent', 'hostess', '@keyframes'))


def test_availability_retry_copy_keeps_original_deadline_and_expiry_severity():
    row = model.Row('automation_cycle', 'Cycle', 'WAITING FOR INPUTS · ATTEMPT 9',
        model.WARN, 'state RETRY_WAIT', NOW, required_current=True,
        recovery=RecoveryEvidence(phase='AUTOMATION_REFRESH_AVAILABILITY',
            automatic=True, attempt=9, deadline=NOW+timedelta(minutes=1)))
    html = _row_html(row, NOW)
    assert 'Automatic retries are continuing before the saved market-open deadline' in html
    assert 'data-status="warn"' in html
    expired = _row_html(row, NOW+timedelta(minutes=2))
    assert 'data-status="fail"' in expired and 'Attention needed' in expired
    assert 'Automatic retries are continuing' not in expired


@pytest.mark.parametrize('buys,sells', [(0,0),(1,0),(0,1),(1,1),(1,2),(2,1),(2,2)])
def test_typed_plan_counts_use_singular_and_plural_without_changing_evidence(buys, sells):
    legs = [dict(security_id=f'b{i}', ticker=f'B{i}', current_quantity='0',
                 target_quantity='1', change_quantity='1', action='BUY') for i in range(buys)]
    legs += [dict(security_id=f's{i}', ticker=f'S{i}', current_quantity='1',
                  target_quantity='0', change_quantity='-1', action='SELL') for i in range(sells)]
    plan = PlanPreview(cycle_id='cycle', plan_id='plan', decision_session=date(2026,10,22),
        effective_session=date(2026,10,23), execute_at=NOW+timedelta(days=1),
        created_at=NOW, observation_at=NOW, legs=legs)
    row = model.Row('paper_plan', 'Next paper plan', 'original recorded counts', model.OK,
                    'original evidence', paper_plan=plan)
    shown = describe(row, model.OK)[1]
    assert shown == (f'2026-10-23 · {buys} {"buy" if buys == 1 else "buys"} · '
                     f'{sells} {"sell" if sells == 1 else "sells"}')
    assert row.value == 'original recorded counts' and row.status == model.OK
    unknown = plan.model_copy(update={'legs': [plan.legs[0].model_copy(update={
        'action': 'UNAVAILABLE'})]}) if plan.legs else None
    if unknown is not None:
        unavailable = model.Row('paper_plan', 'Next paper plan', 'changes unavailable',
                                model.OK, paper_plan=unknown)
        assert describe(unavailable, model.OK)[1] == 'changes unavailable'
