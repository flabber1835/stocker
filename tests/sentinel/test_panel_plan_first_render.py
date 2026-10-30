"""The compact overview keeps the original evidence and authority boundaries."""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
import re

import pytest

from sentinel.operational_status import RecoveryEvidence
from sentinel.panel import model, overview
from sentinel.paper_plan_preview import PlanPreview, PlannedLeg


NOW = datetime(2026, 10, 23, 4, 13, tzinfo=timezone.utc)
OBSERVED = NOW-timedelta(minutes=5)
EXECUTE = NOW.replace(hour=13, minute=31)


def example_panel():
    holdings = [model.ShadowHolding(security_id=f'sid-{index}', ticker=f'STK{index}',
        quantity=Decimal(1), raw_close=Decimal(100), value=Decimal(100),
        weight=Decimal(100)/Decimal(1500)) for index in range(14)]
    slots = [model.ShadowSlot(slot_id=index, state='OCCUPIED',
        security_id=holding.security_id, ticker=holding.ticker,
        model_quantity=holding.quantity, cooldown_total=21,
        exit_pending=index == 0, exit_reason='EXIT_TRAILING_STOP' if index == 0 else None)
        for index, holding in enumerate(holdings)]
    slots += [model.ShadowSlot(slot_id=index, state='COOLING', cooldown_total=21,
              cooldown_elapsed=20 if index == 19 else 9,
              cooldown_remaining=1 if index == 19 else 12) for index in range(14,20)]
    book = model.ShadowBook(session='2026-10-22', cash=Decimal(100),
        receivables=Decimal(0), nav=Decimal(1500), pending_operations=2,
        holdings=holdings, slots=slots)
    legs = [PlannedLeg(security_id='ATI', ticker='ATI', current_quantity=Decimal(8),
            target_quantity=Decimal(0), change_quantity=Decimal(-8), action='SELL'),
        PlannedLeg(security_id='ATEX', ticker='ATEX', current_quantity=Decimal(12),
            target_quantity=Decimal(0), change_quantity=Decimal(-12), action='SELL'),
        PlannedLeg(security_id='PANW', ticker='PANW', current_quantity=Decimal(0),
            target_quantity=Decimal(3), change_quantity=Decimal(3), action='BUY'),
        PlannedLeg(security_id='NAT', ticker='NAT', current_quantity=Decimal(225),
            target_quantity=Decimal(225), change_quantity=Decimal(0), action='HOLD')]
    plan = PlanPreview(cycle_id='cycle-1', plan_id='plan-1',
        decision_session=date(2026,10,22), effective_session=date(2026,10,23),
        execute_at=EXECUTE, created_at=OBSERVED, observation_at=OBSERVED, legs=legs)
    outcome = model.PaperOrderOutcome(security_id='PANW',ticker='PANW', client_key='client-panw-1',
        broker_order_id='native-panw-1',side='BUY',quantity=Decimal(3),filled_quantity=Decimal(0),
        state='CANCELLED',observed_at=NOW-timedelta(hours=8))
    account = model.PaperAccountOverview(account_id='paper-account-1',equity=Decimal(50000),
        cash=Decimal('9635.82'),buying_power=Decimal('9635.82'),observed_at=OBSERVED)
    return model.Panel(now=NOW, rows=[
        model.Row('paper_plan','Next paper plan','ready',model.OK,as_of=OBSERVED,
                  valid_until=EXECUTE,paper_plan=plan,order_outcomes=[outcome]),
        model.Row('alpaca_account','Recorded Alpaca paper account','active',model.OK,
                  as_of=OBSERVED,valid_until=EXECUTE,paper_account=account),
        model.Row('book','Canonical book','14/20',model.OK,as_of=OBSERVED,
                  valid_until=EXECUTE,shadow_book=book),
        model.Row('exposure','Core exposure','0.55',model.OK,as_of=OBSERVED,valid_until=EXECUTE)])


def _with_row(panel,key,**changes):
    return replace(panel,rows=[replace(row,**changes) if row.key == key else row for row in panel.rows])


def test_plan_first_orders_then_recorded_account_then_all_canonical_slots():
    panel = example_panel()
    before = deepcopy(panel)
    html = overview.overview_html(panel)
    assert html.index('next-plan-title') < html.index('account-overview-title') < html.index('core-slots-title')
    assert 'Friday, Oct 23' in html and 'From 6:31 AM Pacific' in html
    assert 'Sell</span><strong class="plan-quantity">8 shares' in html
    assert 'Buy</span><strong class="plan-quantity">3 shares' in html
    assert html.index('data-security-id="PANW"') < html.index('All saved targets')
    assert 'NAT' in html[html.index('All saved targets'):]
    assert 'Previous buy ended unfilled · 0/3 shares filled' in html
    assert 'native-panw-1' in html and 'client-panw-1' in html
    assert 'expired' not in html and 'automatic retry' not in html
    assert '$50,000.00' in html and '$9,635.82' in html and 'Cash · 19.3%' in html
    assert 'Oct 22, 2026 · 9:08 PM Pacific' in html
    assert re.findall(r'data-slot-id="(\d+)"',html) == [str(index) for index in range(20)]
    assert '14 held' in html and '6 cooling' in html and 'Planned Core 55%' in html
    assert 'Exit signalled' in html and '1</strong><span class="slot-state">session left' in html
    assert '12</strong><span class="slot-state">sessions left' in html
    assert panel == before


def test_retained_response_labels_original_facts_without_reclocking():
    panel = example_panel()
    html = overview.overview_html(panel,refresh_pending=True)
    assert 'overview retained-overview' in html
    assert 'Last known overview · refreshing status' in html
    assert 'Oct 22, 2026 · 9:08 PM Pacific' in html
    assert 'Previous buy ended unfilled' in html
    assert panel.row('paper_plan').effective_status(NOW) == model.OK


@pytest.mark.parametrize('key,unavailable,withheld',[
    ('paper_plan','Saved trading plan unavailable.','data-security-id="PANW"'),
    ('alpaca_account','Account totals unavailable.','$9,635.82'),
    ('book','Canonical slots unavailable.','data-slot-id="0"')])
@pytest.mark.parametrize('negative',['fail','unknown','expired','future'])
def test_overview_values_do_not_escape_the_original_row_gate(key,unavailable,withheld,negative):
    panel = example_panel()
    if negative in {'fail','unknown'}:
        panel = _with_row(panel,key,status=negative)
    elif negative == 'expired':
        panel = _with_row(panel,key,valid_until=NOW-timedelta(seconds=1))
    else:
        panel = _with_row(panel,key,as_of=NOW+timedelta(seconds=6))
    html = overview.overview_html(panel)
    if key == 'paper_plan' and negative == 'expired':
        unavailable = 'Next trading plan pending.'
    assert unavailable in html and withheld not in html


def test_source_frontier_wait_shows_only_admitted_historical_slots_until_deadline():
    panel = example_panel()
    deadline = NOW+timedelta(hours=3)
    panel = _with_row(panel,'book',status=model.WARN,required_current=True,
        valid_until=deadline,recovery=RecoveryEvidence(phase='SOURCE_FRONTIER',automatic=True,
                                                       deadline=deadline))
    html = overview.overview_html(panel)
    assert 'Last attested through 2026-10-22 · current session not verified.' in html
    assert 'data-slot-id="19"' in html
    expired = overview.overview_html(replace(panel,now=deadline+timedelta(seconds=1)))
    assert 'Canonical slots unavailable.' in expired and 'data-slot-id=' not in expired


def test_missing_evidence_does_not_invent_twenty_empty_slots_or_zero_balances():
    html = overview.overview_html(model.Panel(now=NOW))
    assert 'Canonical slots unavailable.' in html and 'data-slot-id=' not in html
    assert 'Account totals unavailable.' in html and '$0.00' not in html
    panel = example_panel()
    panel = _with_row(panel,'book',shadow_book=panel.row('book').shadow_book.model_copy(update={'slots':[]}))
    assert 'Canonical slots unavailable.' in overview.overview_html(panel)


def test_plan_is_unavailable_at_the_original_execution_boundary():
    html = overview.overview_html(replace(example_panel(),now=EXECUTE))
    assert 'Next trading plan pending.' in html and 'data-security-id="PANW"' not in html


@pytest.mark.parametrize('state,filled,copy',[
    ('PARTIALLY_FILLED','1','partially filled; remainder not confirmed complete · 1/3'),
    ('UNKNOWN','0','outcome uncertain · 0/3'),
    ('ACKNOWLEDGED','0','recorded as working · 0/3'),
    ('REJECTED','0','rejected · 0/3'),
    ('CANCEL_PENDING','1','cancellation pending · 1/3'),
    ('FILLED','3','filled · 3/3')])
def test_previous_order_states_remain_explicit(state,filled,copy):
    panel = example_panel()
    previous = panel.row('paper_plan').order_outcomes[0]
    previous = previous.model_copy(update={'state':state,'filled_quantity':Decimal(filled)})
    html = overview.overview_html(_with_row(panel,'paper_plan',order_outcomes=[previous]))
    assert copy in html


def test_future_native_account_and_order_evidence_is_not_presented_as_true():
    panel = example_panel()
    account = panel.row('alpaca_account').paper_account.model_copy(update={'observed_at':NOW+timedelta(seconds=6)})
    outcome = panel.row('paper_plan').order_outcomes[0].model_copy(update={'observed_at':NOW+timedelta(seconds=6)})
    panel = _with_row(panel,'alpaca_account',paper_account=account)
    panel = _with_row(panel,'paper_plan',order_outcomes=[outcome])
    html = overview.overview_html(panel)
    assert 'Account totals unavailable.' in html and '$9,635.82' not in html
    assert 'Previous buy' not in html


def test_all_evidence_strings_are_html_escaped():
    panel = example_panel()
    plan = panel.row('paper_plan').paper_plan
    attack = '<script>alert("x")</script>'
    legs = [leg.model_copy(update={'ticker':attack}) if leg.security_id == 'PANW' else leg for leg in plan.legs]
    outcome = panel.row('paper_plan').order_outcomes[0].model_copy(update={'broker_order_id':attack})
    panel = _with_row(panel,'paper_plan',paper_plan=plan.model_copy(update={'legs':legs}),order_outcomes=[outcome])
    html = overview.overview_html(panel)
    assert attack not in html and '&lt;script&gt;' in html and '&quot;x&quot;' in html


def test_guard_falsifier_detects_a_book_bypassing_its_authentication_gate():
    source = inspect.getsource(overview._slots_html)
    needle = 'row.can_show_shadow_book(panel.now)'
    assert source.count(needle) == 1
    namespace = dict(vars(overview))
    exec(compile(source.replace(needle,'True'),'broken-slot-admission','exec'),namespace)
    panel = _with_row(example_panel(),'book',status=model.FAIL)
    assert 'data-slot-id=' not in overview._slots_html(panel)
    with pytest.raises(AssertionError):
        assert 'data-slot-id=' not in namespace['_slots_html'](panel)


def preparing_panel(*, now=NOW, state='ACQUIRING', **changes):
    values = dict(job_id='owned-next-close', decision_session=date(2026,10,22),
        effective_session=date(2026,10,23), state=state, rows_done=1720712,
        components_done=31, created_at=now-timedelta(minutes=20), updated_at=now,
        last_progress_at=now-timedelta(minutes=2), observed_at=now,
        deadline=now+timedelta(hours=1), lease_until=now+timedelta(seconds=35),
        owner_registered=True, fence=4)
    values.update(changes)
    work = model.PreparationWork(**values)
    ingest = model.Row('ingest','Acquisition','OPERATIONAL SNAPSHOT · '+state,model.WARN,
        as_of=now, required_current=True, valid_until=work.deadline,
        recovery=RecoveryEvidence(phase='FEED_INGEST',automatic=True,deadline=work.deadline),
        preparation=work)
    return model.Panel(now=now, rows=[ingest])


def _headline(panel, **options):
    from sentinel.panel.render import render
    return render(panel, **options).split('id="operational-state"',1)[1].split('</span>',1)[0]


@pytest.mark.parametrize('state,stage',[
    ('ACQUIRING','Downloading closing data'), ('STAGING','Preparing downloaded data'),
    ('VALIDATING','Validating market data'), ('READY','Waiting to publish validated data')])
def test_owned_preparation_is_healthy_without_claiming_a_saved_plan(state,stage):
    from sentinel.panel.presentation import dashboard_health
    panel = preparing_panel(state=state)
    before = deepcopy(panel)
    health = dashboard_health(panel)
    assert health['status'] == 'ok' and health['color'] == 'green'
    assert health['label'] == 'Healthy · '+stage and health['plan_readiness'] == 'pending'
    assert health['valid_until'] == (NOW+timedelta(seconds=35)).isoformat()
    assert panel.overall == panel.operational == model.WARN
    assert 'class="state ok"' in _headline(panel)
    html = overview.overview_html(panel)
    assert stage in html and 'Next trading plan: not ready yet.' in html
    assert 'Friday, Oct 23' in html and 'Closing session: 2026-10-22' in html
    assert 'Current-stage rows recorded: 1,720,712. Source components completed: 31.' in html
    assert 'Oct 22, 2026 · 9:11 PM Pacific' in html  # Original progress, not render time.
    assert '%' not in html and 'ETA' not in html and 'Ready to trade' not in html
    assert panel == before


@pytest.mark.parametrize('changes',[
    {'owner_registered':False}, {'fence':0}, {'lease_until':None}, {'lease_until':NOW},
    {'state':'WAIT_SOURCE'}, {'state':'RETRY_WAIT'}])
def test_unowned_expired_or_parked_preparation_stays_amber_without_active_copy(changes):
    from sentinel.panel.presentation import dashboard_health
    panel = preparing_panel(**changes)
    health = dashboard_health(panel)
    assert health['status'] == 'warn' and health['label'].startswith('Preparation delayed')
    assert 'Downloading closing data' not in overview.overview_html(panel)
    assert 'Healthy' not in _headline(panel)


def test_waiting_retry_and_published_work_keep_recorded_stage_without_inventing_calculation():
    from sentinel.panel.presentation import dashboard_health
    retry = preparing_panel(state='RETRY_WAIT',next_retry=NOW+timedelta(minutes=5))
    html = overview.overview_html(retry)
    assert 'Waiting to retry data acquisition' in html and 'Recorded retry:' in html
    assert 'Downloading closing data' not in html
    published = preparing_panel(state='PUBLISHED',owner_registered=False,lease_until=None)
    row = published.rows[0]
    published = replace(published,rows=[replace(row,status=model.OK,recovery=None)])
    assert dashboard_health(published)['label'] == 'Healthy · Market data published · plan preparation pending'
    assert 'Calculating' not in overview.overview_html(published)


def test_atomic_publication_proof_wins_over_the_committed_jobs_old_lease():
    from sentinel.panel.presentation import dashboard_health
    panel = preparing_panel(state='PUBLISHED',owner_registered=False,lease_until=NOW)
    deadline = NOW+timedelta(minutes=2)
    panel = replace(panel,rows=[replace(panel.rows[0],status=model.OK,recovery=None),
        model.Row('shadow_worker','Worker','RUNNING',model.OK,as_of=NOW,
            required_current=True,valid_until=NOW+timedelta(seconds=60)),
        model.Row('feed','Feed','WAITING',model.WARN,as_of=NOW,
            required_current=True,valid_until=deadline,recovery=RecoveryEvidence(
                phase='SOURCE_PUBLICATION',automatic=True,deadline=deadline))])
    health = dashboard_health(panel)
    assert health['label'] == 'Healthy · Publishing closing data'
    assert health['valid_until'] == (NOW+timedelta(seconds=45)).isoformat()
    assert 'Publishing closing data' in overview.overview_html(panel)
    assert 'Downloading closing data' not in _headline(panel)


@pytest.mark.parametrize('negative',[
    model.Row('automation_alerts','Alerts','CURRENT INCIDENT',model.FAIL),
    model.Row('shadow_nav','Metric','UNREADABLE',model.UNKNOWN),
    model.Row('other','Other','UNAVAILABLE',model.UNKNOWN)])
def test_healthy_preparation_never_overrules_any_visible_negative_check(negative):
    from sentinel.panel.presentation import dashboard_health
    panel = preparing_panel()
    panel = replace(panel,rows=[*panel.rows,negative])
    assert dashboard_health(panel)['status'] == 'fail'
    assert '>Needs attention' in _headline(panel) and 'Healthy' not in _headline(panel)


@pytest.mark.parametrize('other',[
    model.Row('other','Other','WAITING',model.WARN),
    model.Row('automation_cycle','Cycle','PREPARING',model.WARN)])
def test_unclassified_waits_need_review_even_beside_a_live_job(other):
    from sentinel.panel.presentation import dashboard_health
    panel = preparing_panel()
    panel = replace(panel,rows=[*panel.rows,other])
    assert dashboard_health(panel)['status'] == 'warn'
    assert 'Needs review' in _headline(panel) and 'Healthy' not in _headline(panel)


def test_expected_future_capabilities_are_neutral_but_an_empty_setup_or_required_pending_is_not_green():
    from sentinel.panel.presentation import dashboard_health
    pending = [model.Row('paper_plan','Next plan','NOT PREPARED',model.PENDING),
        *[model.Row('automation_step_'+key,key,'NOT REACHED',model.PENDING)
          for key in ('prepare','open','transport','reconcile','complete')]]
    panel = preparing_panel()
    panel = replace(panel,rows=[*panel.rows,*pending])
    assert dashboard_health(panel)['status'] == 'ok'
    assert dashboard_health(panel)['plan_readiness'] == 'pending'
    assert panel.operational == model.WARN
    assert dashboard_health(model.Panel(now=NOW,rows=pending))['status'] == 'warn'
    required = model.Row('other','Required','PENDING',model.PENDING,required_current=True)
    assert dashboard_health(replace(panel,rows=[*panel.rows,required]))['status'] == 'fail'


def test_composed_closing_run_has_healthy_acquisition_without_claiming_financial_readiness():
    from sentinel.panel.presentation import dashboard_health
    deadline = NOW+timedelta(hours=1)
    source = RecoveryEvidence(phase='SOURCE_FRONTIER',automatic=True,deadline=deadline)
    cycle = RecoveryEvidence(phase='AUTOMATION_CLOSING_DATA',automatic=True,deadline=deadline)
    verify = RecoveryEvidence(phase='FINANCIAL_VERIFICATION',automatic=True,deadline=deadline)
    panel = preparing_panel()
    rows = [*panel.rows,
        model.Row('shadow_worker','Strategy worker','RUNNING',model.OK,as_of=NOW,
            required_current=True,valid_until=NOW+timedelta(seconds=60)),
        model.Row('shadow_verification','Shadow','WAITING FOR INPUTS',model.WARN,
            as_of=NOW,required_current=True,valid_until=deadline,recovery=source),
        model.Row('feed','Feed','WAITING FOR CLOSING DATA',model.WARN,
            as_of=NOW,required_current=True,valid_until=deadline,recovery=source),
        model.Row('automation_cycle','Cycle','WAITING FOR CLOSING DATA',model.WARN,
            as_of=NOW,required_current=True,valid_until=deadline,recovery=cycle),
        model.Row('automation_step_data','Data','WAITING FOR CLOSING DATA',model.WARN,
            as_of=NOW,required_current=True,valid_until=deadline,recovery=cycle),
        model.Row('paper_reconciliation','Paper','CHECK IN PROGRESS',model.WARN,
            as_of=NOW,required_current=True,valid_until=deadline,recovery=verify),
        model.Row('paper_plan','Next plan','NOT PREPARED',model.PENDING),
        *[model.Row('automation_step_'+key,key,'NOT REACHED',model.PENDING)
          for key in ('prepare','open','transport','reconcile','complete')]]
    panel = replace(panel,rows=rows)
    assert panel.overall == panel.operational == model.WARN
    assert dashboard_health(panel)['label'] == 'Healthy · Downloading closing data'
    assert dashboard_health(panel)['plan_readiness'] == 'pending'
    assert 'Next trading plan: not ready yet.' in overview.overview_html(panel)
    failure = model.Row('automation_alerts','Alerts','CURRENT INCIDENT',model.FAIL)
    assert dashboard_health(replace(panel,rows=[*rows,failure]))['status'] == 'fail'


@pytest.mark.parametrize('fault',[None,'missing_leader','disabled','bare_wait','expired'])
def test_normal_discovery_wait_needs_current_policy_and_live_worker_proof(fault):
    from sentinel.panel.presentation import dashboard_health
    deadline = NOW+timedelta(seconds=20)
    recovery = RecoveryEvidence(phase='AUTOMATION_DISCOVERY',automatic=True,deadline=deadline)
    rows = [model.Row('automation','Automation','ENABLED · KILL RELEASED',model.OK),
        model.Row('automation_leader','Leader','ACTIVE',model.OK,as_of=NOW,
            required_current=True,valid_until=deadline),
        model.Row('automation_cycle','Cycle','WAITING FOR NEXT DECISION',model.WARN,
            required_current=True,recovery=recovery)]
    if fault == 'missing_leader': rows.pop(1)
    elif fault == 'disabled': rows[0] = replace(rows[0],value='DISABLED')
    elif fault == 'bare_wait': rows[-1] = replace(rows[-1],required_current=False,recovery=None)
    panel = model.Panel(now=deadline+timedelta(seconds=1) if fault == 'expired' else NOW,rows=rows)
    if fault is None:
        assert dashboard_health(panel)['label'] == 'Healthy · Waiting for next decision'
        assert dashboard_health(panel)['valid_until'] == deadline.isoformat()
    else:
        assert dashboard_health(panel)['status'] != 'ok'


@pytest.mark.parametrize('change',[
    {'key':'other'}, {'value':'WAITING'}, {'required_current':False},
    {'valid_until':NOW+timedelta(minutes=2)}, {'recovery':None}])
def test_only_the_exact_bounded_financial_check_is_a_normal_health_wait(change):
    from sentinel.panel.presentation import dashboard_health
    deadline = NOW+timedelta(minutes=1)
    row = model.Row('paper_reconciliation','Paper','CHECK IN PROGRESS',model.WARN,
        required_current=True,valid_until=deadline,recovery=RecoveryEvidence(
            phase='FINANCIAL_VERIFICATION',automatic=True,deadline=deadline))
    assert dashboard_health(model.Panel(now=NOW,rows=[row]))['label'] == 'Healthy · Checking paper account'
    assert dashboard_health(model.Panel(now=NOW,rows=[replace(row,**change)]))['status'] != 'ok'


def test_source_errors_and_original_progress_expiry_withdraw_healthy_copy():
    from sentinel.panel.presentation import dashboard_health
    panel = preparing_panel()
    assert dashboard_health(replace(panel,source_errors=['unreadable']))['status'] == 'fail'
    expired = replace(panel,now=NOW+timedelta(seconds=46))
    assert dashboard_health(expired)['status'] != 'ok'
    assert 'preparation-title' not in overview.overview_html(expired)
    assert 'Downloading closing data' not in overview.overview_html(expired)
    assert 'Next trading plan pending.' in overview.overview_html(expired)


def test_preparation_precedes_completed_history_and_yields_to_an_actual_future_plan():
    from test_panel_trading_run import completed_history, NOW as COMPLETED_NOW
    panel = preparing_panel(now=COMPLETED_NOW)
    panel = replace(panel,rows=[*panel.rows,completed_history()])
    html = overview.overview_html(panel)
    assert html.index('preparation-title') < html.index('Today’s trades · completed')
    assert 'The next trading plan is pending.' in html
    current = example_panel()
    current = replace(current,rows=[*current.rows,*preparing_panel().rows])
    html = overview.overview_html(current)
    assert 'preparation-title' not in html
    assert 'Next trading plan: saved for its scheduled market open.' in html
    assert 'data-security-id="PANW"' in html


def test_preparation_copy_escapes_data_and_retained_views_withdraw_current_claims(monkeypatch):
    from sentinel.panel.render import render
    panel = preparing_panel(lease_until=NOW+timedelta(seconds=12))
    html = render(panel)
    assert 'data-max-age-seconds="12.0"' in html
    assert '}, 1000)' in html  # Refresh at one second when only twelve seconds remain.
    retained = render(panel,refresh_pending=True)
    assert 'class="state ok"' not in retained.split('</header>',1)[0]
    assert 'Last known · Downloading closing data' in retained
    assert 'Last known · Next trading plan: not ready yet.' in retained
    attack = '<script>alert("x")</script>'
    monkeypatch.setattr(overview,'preparation_stage',lambda _:attack)
    html = overview.overview_html(panel)
    assert attack not in html and '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;' in html


def test_live_owner_admission_has_an_executed_health_removal_falsifier(monkeypatch):
    from sentinel.panel import presentation
    source = inspect.getsource(presentation._normal_warning)
    guard = 'and row.preparation.active_at(panel.now)'
    assert source.count(guard) == 1
    namespace = dict(vars(presentation))
    exec(compile(source.replace(guard,''),'missing-live-preparation-owner','exec'),namespace)
    monkeypatch.setattr(presentation,'_normal_warning',namespace['_normal_warning'])
    with pytest.raises(AssertionError):
        test_unowned_expired_or_parked_preparation_stays_amber_without_active_copy(
            {'owner_registered':False})
