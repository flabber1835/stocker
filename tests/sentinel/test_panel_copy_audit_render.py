"""The expanded view must describe the displayed evidence without extra claims."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sentinel.panel import model, render
from sentinel.paper_plan_preview import PlanPreview


NOW = datetime(2026, 10, 22, 22, tzinfo=timezone.utc)


def test_guide_discloses_local_profile_without_imposing_it_on_reviewed_operation():
    row = model.Row('shadow_verification', 'Shadow', 'VERIFIED', model.OK)
    local = render.render(model.Panel(rows=[row], now=NOW, local_paper_mode=True))
    other = render.render(model.Panel(rows=[row], now=NOW, local_paper_mode=False))
    for html in (local, other):
        assert 'OpenFIGI classifies eligible equity instruments' in html
        assert 'unscaled stock-selection book' in html
        assert 'Alpaca paper account has its own recorded holdings' in html
    assert 'Backup creation, restore drills and backup verification are disabled' in local
    assert 'Owner-authorized local PAPER operation is active' not in other
    assert 'backup verification are disabled' not in other


def test_dollar_budget_preview_never_claims_an_opening_quote_or_changes_saved_terms():
    plan = PlanPreview(cycle_id='cycle', plan_id='plan',
        decision_session=date(2026, 10, 22), effective_session=date(2026, 10, 23),
        execute_at=NOW + timedelta(hours=15, minutes=31), created_at=NOW,
        observation_at=NOW - timedelta(hours=1), legs=[dict(
            security_id='x', ticker='X', current_quantity=Decimal(0),
            target_quantity=Decimal(0), change_quantity=None,
            opening_dollars=Decimal(2000), action='BUY')])
    before = plan.model_dump()
    row = model.Row('paper_plan', 'Plan', 'ready', model.OK, paper_plan=plan)
    html = render._paper_plan_html(row, NOW)
    assert '$2000 budget' in html and 'Sized at execution' in html
    assert 'selected execution policy' in html and 'funding checks' in html
    assert 'opening quotes' not in html and 'opening prices' not in html
    assert '2026-10-22 at 02:00:00 PM Pacific' in html
    assert 'not orders or fills' in html and plan.model_dump() == before
    assert row.status == model.OK


def test_holdings_expansion_distinguishes_unscaled_weights_and_unspendable_receivables():
    book = model.ShadowBook(session='2026-10-22', cash='90', receivables='10',
        nav='100', pending_operations=2, holdings=[])
    row = model.Row('book', 'Book', 'ready', model.OK, shadow_book=book)
    html = render._holdings_html(row, NOW)
    assert 'Unscaled Wealth Core' in html
    assert 'Core allocation, Treasury-bill sleeve and transaction costs' in html
    assert 'not the Alpaca account' in html
    assert 'no longer held' in html and 'not spending cash' in html
    assert '$90.00' in html and '$10.00' in html
    assert '2 pending strategy operations' in html
    assert book.cash == 90 and book.receivables == 10 and book.nav == 100


def test_browser_subscription_and_sender_acceptance_do_not_claim_device_receipt():
    script = render.PUSH_SCRIPT
    assert 'This browser has a notification subscription. Send a test to check delivery.' in script
    assert 'Test accepted by the push service. Check this device' in script
    assert 'Check Alert delivery' not in script
    assert 'Check Notification delivery' in script
    assert 'Notifications enabled on this device.' not in script
