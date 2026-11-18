from decimal import Decimal

import pytest

from sentinel.panel import overview, sources
from sentinel.execution import journal
from tests.sentinel.test_panel_plan_first_render import NOW, OBSERVED, _with_row, example_panel
from tests.sentinel.test_unconfirmed_paper_postings import conn, incident, pg


def evidence(monkeypatch, **changes):
    import sentinel.paper.cash_postings as cash_postings

    status = dict(plan_id='current', broker='alpaca', account_id='paper-account-1',
                  observed_at=OBSERVED.isoformat(), account_cash='7064.26',
                  buying_power='7064.26', reserve='0.01',
                  events={'dividend': '6.25', 'fee': '-0.01'})
    monkeypatch.setattr(sources, '_current_plan', lambda conn: {'plan_id': 'current'})
    monkeypatch.setattr(cash_postings, 'read_posting_status',
                        lambda conn, **kw: {**status, **changes})
    return sources._cash_posting_overview(None, account_id='paper-account-1', now=NOW)


def test_dashboard_explains_both_cash_events_without_spending_the_credit(monkeypatch):
    posting = evidence(monkeypatch)
    assert posting.observed_at == OBSERVED
    assert posting.funding_ceiling == Decimal('7064.25')
    panel = example_panel()
    account = panel.row('alpaca_account').paper_account.model_copy(update={'cash_posting': posting})
    panel = _with_row(panel, 'alpaca_account', paper_account=account)
    html = overview.overview_html(panel)
    assert 'unconfirmed credits were $6.25 and reserved debits were $0.01' in html
    assert '$7,064.25' in html
    assert 'Cash last checked:' in html


@pytest.mark.parametrize('change', [{'account_id': 'other'}, {'plan_id': 'superseded'},
                                    {'reserve': '0'}, {'observed_at': '2099-11-18T00:00:00Z'}])
def test_foreign_or_incoherent_posting_cannot_explain_cash(monkeypatch, change):
    with pytest.raises(ValueError):
        evidence(monkeypatch, **change)


def test_resolved_cash_events_remove_the_note(monkeypatch):
    assert evidence(monkeypatch, events={}, reserve='0') is None


def test_account_card_follows_the_current_postgres_posting_record(conn, incident):
    plan, state, observe = incident
    journal.save_plan(conn, plan)
    def current():
        return sources._cash_posting_overview(
            conn, account_id=plan.broker_account_id, now=state.processed_through)
    observe(plan, '7064.26')
    pending = current()
    assert (pending.credit, pending.reserved_debit, pending.funding_ceiling) == (
        Decimal('6.25'), Decimal('0.01'), Decimal('7064.25'))
    observe(plan, '7070.51')
    assert current().credit == 0 and current().reserved_debit == Decimal('0.01')
    observe(plan, '7070.50')
    assert current() is None
