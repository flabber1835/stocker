"""One immutable upcoming intent across midnight and receipt refreshes."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest

from sentinel.panel import model, overview, serialization
from test_panel_plan_first_render import example_panel


def upcoming(*, different=False):
    page = example_panel()  # After Eastern midnight, before Pacific midnight.
    intent = page.row('paper_plan').paper_plan
    if different:
        intent = intent.model_copy(update={'plan_id': 'another-plan'})
    run = model.TradingRun(intent=intent, state='WAITING_OPEN',
                           updated_at=page.now, orders=[])
    return replace(page, rows=[*page.rows, model.Row('trading_run', 'Run',
        'WAITING_OPEN', model.OK, as_of=page.now,
        valid_until=intent.execute_at, trading_run=run)])


def test_midnight_does_not_duplicate_the_same_pending_plan():
    page = upcoming()
    assert page.row('trading_run').can_show_trading_run(page.now)
    html = overview.overview_html(page)
    assert html.count('Next trading plan</h2>') == 1
    assert 'Today’s trading plan' not in html
    assert html.count('data-security-id="ATI"') == 1


def test_distinct_run_remains_distinct_from_the_upcoming_intent():
    html = overview.overview_html(upcoming(different=True))
    assert 'Next trading plan</h2>' in html and 'Today’s trading plan' in html


def test_same_intent_does_not_hide_an_execution_or_failed_run():
    page=upcoming()
    for state in ('EXECUTING','FAILED'):
        run=page.row('trading_run')
        changed=replace(run,trading_run=run.trading_run.model_copy(update={'state':state}))
        html=overview.overview_html(replace(page,rows=[changed if row is run else row for row in page.rows]))
        assert 'Today’s trading plan' in html


@pytest.mark.parametrize('scope', ['PAPER', 'SHADOW'])
def test_partial_refresh_keeps_dated_intent_without_current_payload_or_countdown(scope):
    page = replace(upcoming(), observation_current=False,
                   observation_changed_scopes=(scope,))
    before = deepcopy(page)
    html = overview.overview_html(page)
    assert 'Last known saved plan · status refreshing.' in html
    assert 'Market-open time not current' in html
    assert 'Market open in ' not in html
    assert 'Next trading plan · preparing' not in html
    assert 'Today’s trading plan' not in html
    assert 'data-current="false" class="overview-card scope-not-current next-plan"' in html
    payload = serialization.public_payload(page)
    assert next(row for row in payload['rows'] if row['key']=='paper_plan')['paper_plan'] is None
    assert payload['dashboard_health']['color'] != 'green'
    assert '$50,000.00' in html and 'Account snapshot:' in html
    assert ('Last known account' in html) == (scope == 'PAPER')
    assert page == before


@pytest.mark.parametrize('defect', ['expired', 'fail', 'unknown', 'future'])
def test_retention_cannot_resurrect_invalid_or_expired_original_intent(defect):
    page = upcoming()
    row = page.row('paper_plan')
    changes = ({'valid_until': page.now-timedelta(seconds=1)} if defect=='expired' else
               {'as_of': page.now+timedelta(seconds=6)} if defect=='future' else
               {'status': defect})
    page = replace(page, observation_current=False, observation_changed_scopes=('PAPER',),
        rows=[replace(item, **changes) if item is row else item for item in page.rows])
    html = overview.overview_html(page)
    assert 'Last known saved plan' not in html
    assert 'data-security-id="ATI"' not in html
