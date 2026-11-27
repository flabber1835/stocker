from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from sentinel.panel import model
from sentinel.panel.render import render
from sentinel.panel.run_progress import order_summary
from sentinel.panel.sources import trading_environment_row
from test_panel_plan_first_render import example_panel, preparing_panel
from test_panel_trading_run import NOW, TERMS, run


def order(security, index, state, *, native=False, filled=0):
    return model.RunOrder(security_id=security, ticker=security, client_key=f'key-{index}',
        broker_order_id=f'native-{index}' if native else None, side='BUY', notional=Decimal('12.34'),
        filled_quantity=Decimal(filled), filled_average_price=Decimal('4.20') if filled else None,
        state=state, observed_at=NOW, order_terms=TERMS)


def page(orders, state):
    intent = run().intent
    template = next(leg for leg in intent.legs if leg.action == 'BUY')
    legs = {item.security_id: template.model_copy(update=dict(security_id=item.security_id, ticker=item.ticker))
            for item in orders}
    intent = intent.model_copy(update={'legs': list(legs.values()) or [template]})
    recorded = model.TradingRun(intent=intent, state=state, updated_at=NOW, orders=orders,
        completed_at=NOW if state in {'SUPERSEDED', 'SUCCEEDED'} else None)
    row = model.Row('trading_run', 'Today’s trading', state, model.FAIL if state == 'SUPERSEDED' else model.WARN,
                    as_of=NOW, valid_until=NOW+timedelta(hours=3), trading_run=recorded)
    return model.Panel(now=NOW, rows=[row])


def test_incomplete_open_shows_confirmed_counts_at_top_and_in_run_without_inventing_unsent_proof():
    orders = [order(f'STK{i}', i, 'FILLED', native=True, filled='2.9') for i in range(18)]
    orders += [order(f'STK{i}', i, 'PLANNED') for i in (18, 19)]
    panel = page(orders, 'SUPERSEDED')
    html = render(panel)
    summary = '20 recorded orders · 18 confirmed sent · 18 fully filled · 2 still planned'
    assert summary in html.split('</header>')[0]
    assert f'<p class="run-order-counts">{summary}</p>' in html
    assert 'Today’s run · superseded' in html
    planned = html.split('class="plan-ticker">STK19</strong>', 1)[1].split('</li>', 1)[0]
    assert 'Planned · no confirmed submission</p>' in planned
    assert '$12.34 requested' not in planned.split('<details', 1)[0]
    assert 'unsent remainder at cutoff' not in html


def test_working_basket_and_restarted_pending_sends_use_distinct_durable_commands():
    orders = [order('AAA', 1, 'ACKNOWLEDGED', native=True), order('BBB', 2, 'PARTIALLY_FILLED', native=True, filled='1.4'),
              order('CCC', 3, 'SEND_PENDING'), order('DDD', 4, 'UNKNOWN')]
    panel = page(orders, 'EXECUTING')
    summary = '4 recorded orders · 2 confirmed sent · 0 fully filled · 2 working · 1 awaiting submission confirmation · 1 with outcome unknown'
    html = render(panel)
    assert summary in html
    assert 'Broker reconciliation must confirm the outstanding orders before a retry.' in html
    restored = model.TradingRun.model_validate_json(panel.rows[0].trading_run.model_dump_json())
    assert order_summary(restored) == summary
    unknown = order('EEE', 5, 'UNKNOWN', native=True)
    assert order_summary(page([unknown], 'RECONCILING').rows[0].trading_run) == '1 recorded order · 1 confirmed sent · 0 fully filled · 1 with outcome unknown'


def test_partial_bil_orders_count_commands_without_counting_a_position_or_equating_target_to_fills():
    panel = page([order('BIL', 1, 'FILLED', native=True, filled='0.12'),
                  order('BIL', 2, 'ACKNOWLEDGED', native=True)], 'RECONCILING')
    broker = model.broker_row(available=True, positions=5, completeness='COMPLETE', runtime_state='RUNNING',
                              working_orders=0, as_of=NOW-timedelta(minutes=2))
    html = render(replace(panel, rows=[broker, *panel.rows]))
    assert '2 recorded orders · 2 confirmed sent · 1 fully filled · 1 working' in html
    assert '5 positions · 0 working in the Oct 23, 06:32:15 AM Pacific broker snapshot' in html


def test_proved_unsent_remainder_counts_trades_without_overstating_the_number_of_commands():
    recorded = page([order('CASH', 1, 'FILLED', native=True, filled='2.9'),
                     order('BUY', 2, 'PLANNED')], 'SUPERSEDED').rows[0].trading_run
    proved = model.TradingRun.model_validate(dict(recorded.model_dump(), unsent_at_cutoff={
        'BUY': {'side': 'BUY', 'notional': '12.34'}, 'CASH': {'side': 'BUY', 'notional': '2.05'}}))
    assert order_summary(proved) == ('2 recorded orders · 1 confirmed sent · 1 fully filled · 1 still planned · '
                                     '2 trades with an unsent remainder at cutoff')


@pytest.mark.parametrize('with_run', [True, False])
def test_missing_commands_and_unavailable_run_do_not_infer_counts_from_plan(with_run):
    panel = page([], 'SUPERSEDED')
    if not with_run:
        panel = replace(panel, rows=[replace(panel.rows[0], trading_run=None)])
    html = render(panel).split('</header>', 1)[0]
    expected = 'No orders recorded. Submission and fill counts are unavailable.' if with_run else 'Order counts unavailable.'
    assert expected in html
    assert '0 confirmed sent' not in html


@pytest.mark.parametrize('endpoint,mode,account', [
    ('https://api.alpaca.markets', 'LIVE', 'Recorded live account'),
    ('https://paper-api.alpaca.markets', 'PAPER', 'Recorded paper account'),
    ('https://invalid.test', 'UNCONFIRMED', 'Recorded account · mode unconfirmed'),
])
def test_selected_account_mode_labels_each_trading_card(endpoint, mode, account):
    from sentinel.panel.overview import overview_html

    selected = trading_environment_row(endpoint)
    panels = [(example_panel(), 'next-plan-title'), (preparing_panel(), 'preparation-title'),
              (page([order('BIL', 1, 'ACKNOWLEDGED', native=True)], 'EXECUTING'), 'current-trades-title')]
    for panel, heading in panels:
        document = overview_html(replace(panel, rows=[selected, *panel.rows]))
        card = document.split(f'aria-labelledby="{heading}"', 1)[1].split('</section>', 1)[0]
        assert f'<span class="overview-tag">{mode}</span>' in card
        assert account in document
        if mode != 'PAPER':
            assert 'class="overview-tag">PAPER<' not in document


def refused_panel(*, code='PURCHASES_REQUIRE_DATABASE_ANCHOR', state='RECONCILING', **overrides):
    from sentinel.panel import serialization

    panel = page([], 'RECONCILING')
    intent = panel.row('trading_run').trading_run.intent
    fields = dict(installed=True, enabled=True, cycle_id=intent.cycle_id, plan_id=intent.plan_id,
                  state=state, updated_at=NOW, failure_code=code, failure_detail='0 submitted, check <failed>')
    cycle = model.automation_cycle_row(**(fields | overrides))
    unrelated = model.Row('paper_reconciliation', 'Paper account', 'Unable to read verification',
                          model.UNKNOWN, required_current=True)
    panel = replace(panel, rows=[unrelated, cycle, *panel.rows])
    public_cycle = next(row for row in serialization.public_payload(panel)['rows'] if row['key'] == cycle.key)
    return panel, public_cycle


@pytest.mark.parametrize('state', ['RECONCILING', 'RETRY_WAIT', 'BLOCKED', 'SUPERSEDED'])
def test_current_purchase_refusal_precedes_secondary_unknown_without_changing_its_verdict(state):
    panel, public = refused_panel(state=state)
    reason = 'Purchases withheld. An operator must verify the recovery history of this database and broker account before Sentinel can buy.'
    header = render(panel).split('</header>', 1)[0]
    assert public['value'] == state and public['display_value'] == reason
    assert header.index(reason) < header.index('Unable to read verification')


def test_legacy_record_quotes_only_the_actual_attempt_and_preserves_unknowns():
    panel, public = refused_panel(code='ACTIONABLE_DELTA_REMAINS')
    assert public['display_value'] == 'Last execution attempt: 0 submitted, check <failed>'
    header = render(panel).split('</header>', 1)[0]
    assert 'Last execution attempt: 0 submitted, check &lt;failed&gt;' in header
    assert 'Unable to read verification' in header and 'Purchases withheld' not in header


@pytest.mark.parametrize('changes', [
    {'plan_id': 'previous-plan'}, {'cycle_id': 'previous-cycle'}, {'enabled': False},
    {'state': 'SUCCEEDED'}, {'state': 'EXECUTING', 'failure_code': None},
    {'updated_at': NOW+timedelta(hours=1)}, {'failure_code': 'OTHER_REASON'},
])
def test_previous_foreign_or_unverified_reason_cannot_claim_current_purchases_are_withheld(changes):
    panel, public = refused_panel(**changes)
    assert 'display_value' not in public
    assert 'Purchases withheld' not in render(panel).split('</header>', 1)[0]


def test_newer_current_success_and_retained_or_expired_observation_do_not_repeat_a_refusal():
    from sentinel.panel.run_progress import current_execution_refusal

    panel, _ = refused_panel()
    run_row = panel.row('trading_run')
    finished = replace(run_row, trading_run=run_row.trading_run.model_copy(
        update={'state': 'SUCCEEDED', 'updated_at': NOW+timedelta(seconds=1)}))
    later = replace(panel, now=NOW+timedelta(seconds=1), rows=[panel.row('automation_cycle'), finished])
    for view in (later, replace(panel, observation_current=False, observation_retained=True),
                 replace(panel, observation_valid_until=NOW),
                 replace(panel, rows=[replace(panel.row('automation_cycle'), valid_until=NOW-timedelta(seconds=1))])):
        assert current_execution_refusal(view) is None
    assert 'Purchases withheld' not in render(panel, refresh_pending=True).split('</header>', 1)[0]


def test_healthy_operational_facts_keep_their_original_wire_shape():
    values = model.OperationalFact(kind='AUTOMATION_CYCLE', state='EXECUTING').model_dump(mode='json')
    assert 'execution_refusal' not in values
