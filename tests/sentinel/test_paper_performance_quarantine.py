"""Unsupported paper cash permanently loses strategy-performance authority."""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import paper_performance as P
from test_issue211_trial_verification import JsonStateConnection


def result(*, session="2026-08-20", dividends=True, account="PA-1", epoch=1):
    return {
        "session": session, "verdict": "VERIFIED", "reason_codes": [],
        "binding": {"deployment_id": "test", "broker": "alpaca",
                    "broker_account_id": account, "takeover_epoch": epoch},
        "paper_limitations": {"expected_dividends": [{
            "security_id": "P:AAA", "ticker": "AAA", "accrued_session": "2026-08-20",
            "shares": "100", "per_share": "10", "amount": "1000",
            "source_row_ids": ["source-dividend"]}] if dividends else []},
        "account_evidence": {"account": {"cash": "20000", "equity": "100000"}},
        "cash": {"rows": [], "external": "0", "internal": "0"},
        "performance": {"strategy_pl": "100", "daily_return": "0.01",
                        "cumulative_factor": "1.1", "total_return": "0.1"},
    }


def test_first_dividend_latches_invalidity_and_preserves_separate_evidence():
    conn = JsonStateConnection()
    before = result()
    actual = P.record_and_project(conn, before)
    marker = P.load(conn, before["binding"])
    assert marker["performance_valid"] is False
    assert marker["canonical_entitlements"][0]["amount"] == "1000"
    assert marker["observed_broker_account"]["cash"] == "20000"
    assert marker["broker_cash_evidence"]["rows"] == []
    assert marker["synthetic_adjustment"] is None
    assert actual["performance"]["strategy_pl"] is None
    assert actual["performance"]["total_return"] is None
    assert actual["account_evidence"] == before["account_evidence"]


def test_restart_repeated_processing_later_credit_and_new_epoch_cannot_clear_marker():
    conn = JsonStateConnection()
    first = P.record_and_project(conn, result())
    assert P.record_and_project(conn, result()) == first
    assert len(conn.rows) == 1
    restarted = JsonStateConnection()
    restarted.rows = deepcopy(conn.rows)
    later = result(session="2026-08-24", dividends=False, epoch=2)
    later["account_evidence"]["account"]["cash"] = "21000"
    later["cash"]["rows"] = [{"amount": "1000", "source": "BROKER"}]
    actual = P.record_and_project(restarted, later)
    assert actual["verdict"] == "NOT_VERIFIED"
    assert actual["performance"]["performance_valid"] is False
    assert actual["performance"]["invalid_since"] == "2026-08-20"
    assert P.record_and_project(restarted, result(dividends=False, account="PA-2"))["verdict"] == "VERIFIED"


def test_tampered_quarantine_refuses_and_empty_account_never_gets_synthetic_credit():
    from sentinel.trial import TrialEvidenceRefused
    conn = JsonStateConnection()
    assert P.record_and_project(conn, result(dividends=False))["verdict"] == "VERIFIED"
    P.record_and_project(conn, result())
    key = P.cursor(result()["binding"])
    conn.rows[key][1]["performance_valid"] = True
    with pytest.raises(TrialEvidenceRefused, match="quarantine is malformed"):
        P.load(conn, result()["binding"])


def test_terminal_failure_retains_permanent_negative_authority():
    conn = JsonStateConnection()
    P.record_and_project(conn, result())
    failure = result(session="2026-08-21", dividends=False)
    failure["verdict"] = "NOT_VERIFIED"
    failure["reason_codes"] = ["CYCLE_FAILED"]
    projected = P.record_and_project(conn, failure)
    assert projected["reason_codes"] == [P.REASON, "CYCLE_FAILED"]
    assert projected["performance"]["cumulative_factor"] is None


class OwnershipConnection(JsonStateConnection):
    def __init__(self, fills):
        super().__init__()
        self.fills = fills

    def execute(self, statement, params=()):
        if "FROM sentinel_fills f JOIN sentinel_commands c" in statement:
            assert params == ("alpaca", "PA-1")
            self.result = self.fills
        elif statement.startswith("SELECT DISTINCT session FROM sentinel_active_actions"):
            self.result = [(date(2026, 8, 20),)]
        elif statement.startswith("SELECT security_id,ticker,close_signal"):
            self.result = [("P:AAA", "AAA", 100, 100, 10)]
        elif "COALESCE(source_payload->>'value'" in statement:
            self.result = [(date(2026, 8, 20), "dividend", "AAA", "10", "source-dividend")]
        elif "WHERE UPPER(ticker)='BIL'" in statement:
            self.result = []
        else:
            super().execute(statement, params)


@pytest.mark.parametrize("opening_buy", [False, True])
def test_preparation_detects_missed_cycle_dividend_using_preopen_ownership(monkeypatch, opening_buy):
    # An ex-date opening buy is not entitled; a pre-existing holding sold
    # during the ex-date remains entitled even after a missed trial callback.
    bought = datetime(2026, 8, 20 if opening_buy else 19, 13, 30, tzinfo=timezone.utc)
    fills = [("P:AAA", "BUY", 100, bought),
             ("P:AAA", "SELL", 100, datetime(2026, 8, 20, 14, tzinfo=timezone.utc))]
    conn = OwnershipConnection(fills)
    monkeypatch.setattr("sentinel.execution.reconcile.corpus_action_lookup",
                        lambda *_args, **_kw: lambda *_: Decimal(1))
    monkeypatch.setattr("sentinel.feed.publication.require_current",
                        lambda _: SimpleNamespace(to_dict=lambda: {"version": 7}))
    marker = P.scan_entitlements(
        conn, binding=result()["binding"], through=date(2026, 8, 24),
        account=SimpleNamespace(cash=20000, equity=100000))
    if opening_buy:
        assert marker is None
        assert not conn.rows
    else:
        assert marker["first_affected_session"] == "2026-08-20"
        assert marker["canonical_entitlements"][0]["amount"] == "1000"
        assert marker["canonical_entitlements"][0]["source_row_ids"] == ["source-dividend"]
        # After restart, even source removal cannot restore performance authority.
        conn.fills = []
        assert P.scan_entitlements(
            conn, binding=result(epoch=2)["binding"], through=date(2026, 8, 25),
            account=SimpleNamespace(cash=21000, equity=101000)) == marker


def test_paper_dividend_evidence_uses_reviewed_tri_cash_with_raw_source_retained():
    from fractions import Fraction
    from sentinel.trial import _expected_effective_equity_dividends

    class TriConnection(OwnershipConnection):
        def execute(self, statement, params=()):
            if statement.startswith("SELECT security_id,ticker,close_signal"):
                self.result = [("P:TRI", "TRI", 100, 100,
                                Decimal(str(float(Fraction(1435518, 984560)))))]
            elif "COALESCE(source_payload->>'value'" in statement:
                self.result = [(date(2026, 5, 4), "dividend", "TRI", "1.36", "raw-tri")]
            else:
                super().execute(statement, params)

    expected = _expected_effective_equity_dividends(
        TriConnection([]), date(2026, 5, 4), {"P:TRI": Decimal("98.456")}, [])
    assert Decimal(expected[0]["amount"]) == pytest.approx(Decimal("143.5518"))
    assert expected[0]["reported_per_share"] == "1.36"
    assert expected[0]["source_row_ids"] == ["raw-tri"]
    assert expected[0]["adjudications"][0]["event_id"] == "TRI:2026-05-04:dividend"
