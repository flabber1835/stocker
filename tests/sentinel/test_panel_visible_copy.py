from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import inspect
import textwrap

import pytest

from sentinel.operational_status import RecoveryEvidence
from sentinel.panel import model
from sentinel.panel import presentation
from sentinel.panel.presentation import describe
from sentinel.panel.styles import CSS
from sentinel.panel.render import _row_html, render
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
        required_current=True, valid_until=NOW+timedelta(minutes=1), recovery=RecoveryEvidence(
            phase='SOURCE_FRONTIER', automatic=True,
            deadline=NOW+timedelta(minutes=1)))
    html = _row_html(row, NOW)
    assert 'data-status="warn"' in html
    assert '<div class="value">Preparing closing data</div>' in html
    assert 'Market data for the next decision is still pending' in html
    assert 'Current-session verification must wait' in html
    assert 'keep their original attestation date' in html
    assert 'This result is unverified' in html
    assert 'Original preparation deadline: 2026-10-22 at 03:01 PM Pacific.' in html
    assert row.value == 'WAITING FOR INPUTS · owed 2026-10-22'
    expired = _row_html(row, NOW+timedelta(minutes=2))
    assert 'data-status="fail"' in expired and 'Attention needed' in expired
    assert 'Market data for the next decision is still pending' not in expired
    spoof = model.Row('shadow_verification', 'Shadow verification', row.value,
                     model.WARN, row.detail)
    assert 'Market data for the next decision is still pending' not in describe(spoof, model.WARN)[2]


@pytest.mark.parametrize('key,phase', [
    ('shadow_verification', 'SOURCE_FRONTIER'),
    ('feed', 'POST_CLOSE_SOURCE_WAIT'),
    ('ingest', 'SOURCE_PUBLICATION'),
    ('paper_reconciliation', 'SOURCE_PUBLICATION'),
])
def test_preparing_copy_uses_only_bounded_current_structured_source_waits(key, phase):
    row = model.Row(key, 'Recorded label', 'RECORDED WAIT', model.WARN,
        'original progress and evidence', NOW, required_current=True,
        valid_until=NOW+timedelta(minutes=1), recovery=RecoveryEvidence(
            phase=phase, automatic=True, deadline=NOW+timedelta(minutes=1)))
    html = _row_html(row, NOW)
    assert '<div class="value">Preparing closing data</div>' in html
    assert 'Recorded label · RECORDED WAIT<br>original progress and evidence' in html
    assert 'data-status="warn"' in html
    assert 'Preparing closing data' not in _row_html(row, NOW+timedelta(minutes=2))
    for invalid in (
            replace(row, recovery=None), replace(row, required_current=False),
            replace(row, valid_until=None), replace(row, as_of=None),
            replace(row, valid_until=NOW+timedelta(seconds=30)),
            replace(row, recovery=replace(row.recovery, automatic=False)),
            replace(row, recovery=replace(row.recovery, operator_required=True)),
            replace(row, recovery=replace(row.recovery, phase='FEED_INGEST')),
            replace(row, key='broker')):
        assert not presentation.is_closing_data_preparation(invalid, invalid.effective_status(NOW)), \
            'unproved wait earned preparation copy'


def test_preparation_keeps_historical_book_value_and_current_unverified_caveat():
    row = model.Row('book', 'Book', 'LAST ATTESTED THROUGH 2026-10-21 · 12 stocks', model.WARN,
        'LAST ATTESTED THROUGH 2026-10-21 · CURRENT SESSION NOT VERIFIED',
        NOW-timedelta(days=1), required_current=True, valid_until=NOW+timedelta(minutes=1),
        recovery=RecoveryEvidence(phase='SOURCE_FRONTIER', automatic=True,
            deadline=NOW+timedelta(minutes=1)))
    html = _row_html(row, NOW)
    assert '<div class="value">LAST ATTESTED THROUGH 2026-10-21 · 12 stocks</div>' in html
    assert 'Preparing closing data.' in html and 'keep their original attestation date' in html
    assert 'CURRENT SESSION NOT VERIFIED' in html


def test_preparation_headline_requires_it_to_explain_every_operational_warning():
    row = model.Row('shadow_verification', 'Shadow', 'WAITING FOR INPUTS', model.WARN,
        as_of=NOW, required_current=True, valid_until=NOW+timedelta(minutes=1),
        recovery=RecoveryEvidence(phase='SOURCE_FRONTIER', automatic=True,
            deadline=NOW+timedelta(minutes=1)))
    def headline(rows, **kwargs):
        rows = [model.Row('shadow_worker', 'Worker', 'RUNNING', model.OK,
            as_of=NOW, required_current=True, valid_until=NOW+timedelta(minutes=1)), *rows]
        page = render(model.Panel(rows=rows, now=NOW, **kwargs))
        return page.split('id="operational-state"', 1)[1].split('</span>', 1)[0]
    assert '>Healthy · Waiting for closing data' in headline([row])
    for other in (
            model.Row('other', 'Other', 'FAILED', model.FAIL),
            model.Row('other', 'Other', 'UNAVAILABLE', model.UNKNOWN),
            model.Row('shadow_nav', 'NAV', 'UNAVAILABLE', model.UNKNOWN),
            model.Row('other', 'Other', 'WAITING', model.WARN),
            model.Row('automation_cycle', 'Cycle', 'WAITING FOR INPUTS', model.WARN,
                as_of=NOW, required_current=True, recovery=RecoveryEvidence(
                    phase='AUTOMATION_REFRESH_AVAILABILITY', automatic=True,
                    deadline=NOW+timedelta(minutes=1)))):
        assert '>Healthy' not in headline([row, other])
    assert '>Healthy' not in headline([row], source_errors=['unreadable'])
    assert '>Healthy' not in headline([replace(row,
        valid_until=NOW-timedelta(seconds=1), recovery=replace(row.recovery,
            deadline=NOW-timedelta(seconds=1)))])
    refreshing = render(model.Panel(rows=[row], now=NOW), refresh_pending=True)
    assert '>Refreshing status · last known values</span>' in refreshing


def test_removing_structured_phase_guard_is_detected(monkeypatch):
    source = textwrap.dedent(inspect.getsource(presentation.is_closing_data_preparation))
    guard = 'and recovery.phase in _CLOSING_DATA_PHASES'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'and True'), '<closing-copy-falsifier>', 'exec'),
         presentation.__dict__, namespace)
    monkeypatch.setattr(presentation, 'is_closing_data_preparation',
                        namespace['is_closing_data_preparation'])
    with pytest.raises(AssertionError, match='unproved wait'):
        test_preparing_copy_uses_only_bounded_current_structured_source_waits(
            'feed', 'POST_CLOSE_SOURCE_WAIT')


def test_current_styles_keep_narrow_screen_values_and_accessibility_without_decoration():
    assert '@media(max-width:360px){.value{font-size:16px}}' in CSS
    assert 'prefers-reduced-motion:reduce' in CSS and 'animation:none!important' in CSS
    assert 'summary:focus-visible,a:focus-visible' in CSS
    assert 'repeat(2,minmax(0,1fr))' in CSS
    assert all(name not in CSS for name in ('casino-stage', 'casino-accent', 'hostess', '@keyframes'))


@pytest.mark.parametrize('shadow',[False,True])
def test_existing_brand_graphic_replaces_duplicate_header_text_but_keeps_accessible_name(shadow):
    from html.parser import HTMLParser
    from sentinel.panel.pwa import SERVICE_WORKER

    class Header(HTMLParser):
        active=False

        def __init__(self):
            super().__init__()
            self.images=[];self.headings=[];self.visible=[]

        def handle_starttag(self,tag,attrs):
            if tag=='header':self.active=True
            if self.active and tag=='img':self.images.append(dict(attrs))
            if self.active and tag=='h1':self.headings.append(tag)

        def handle_endtag(self,tag):
            if tag=='header':self.active=False

        def handle_data(self,data):
            if self.active:self.visible.append(data)

    rows=([model.shadow_verification_row(verdict='SHADOW_GO',verification='VERIFIED',
                                        session='2026-10-22')] if shadow else [])
    html=render(model.Panel(now=NOW,rows=rows))
    header=Header();header.feed(html)
    assert header.images==[
        {'data-banner-src':'/static/caesars-palace-512.png','width':'512',
         'height':'512','alt':"Caesar's Palace",'hidden':None},
        {'src':'/static/caesars-palace-512.png','width':'512',
         'height':'512','alt':"Caesar's Palace"},
    ]
    assert '<noscript><img src="/static/caesars-palace-512.png"' in html
    assert '<span class="brand-fallback" hidden>' in html
    assert not header.headings
    visible=' '.join(header.visible)
    assert "CAESAR'S PALACE" not in visible and 'Sentinel · PAPER' not in visible
    assert "<title>Caesar's Palace</title>" in html
    assert "apple-mobile-web-app-title\" content=\"Caesar's Palace\"" in html
    assert 'href="/static/caesars-palace-180.png"' in html
    assert '/static/caesars-palace-192.png' in SERVICE_WORKER  # Push icon is unchanged.


def test_brand_graphic_uses_available_width_and_preserves_its_intrinsic_aspect_ratio():
    import re
    declaration=re.search(r'\.brand img\{([^}]+)\}',CSS).group(1)
    properties=dict(item.split(':',1) for item in declaration.split(';') if item)
    assert properties['display']=='block'
    assert properties['width']=='100%' and properties['max-width']=='100%'
    assert properties['height']=='auto'
    assert '.brand{display:block}' in CSS
    assert 'width:42px' not in declaration and 'height:42px' not in declaration


def test_availability_retry_copy_keeps_original_deadline_and_expiry_severity():
    row = model.Row('automation_cycle', 'Cycle', 'WAITING FOR INPUTS · ATTEMPT 9',
        model.WARN, 'state RETRY_WAIT', NOW, required_current=True,
        recovery=RecoveryEvidence(phase='AUTOMATION_REFRESH_AVAILABILITY',
            automatic=True, attempt=9, deadline=NOW+timedelta(minutes=1)))
    html = _row_html(row, NOW)
    assert 'Automatic retries are continuing before the saved market-open deadline' in html
    assert 'Preparing closing data' not in html
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
