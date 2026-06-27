"""Safety regression tests for the risk-service hardening fixes.

Covers:
  - Daily-loss baseline: when NO same-day opening baseline exists, the loss check
    is UNAVAILABLE → reject (default to safety), NOT silently neutralized by
    falling back to current equity.
  - C2 turnover TOCTOU: in-flight 'pending' sell notional COUNTS toward the daily
    turnover cap (the SQL filters on a positive working/filled status list).
"""
import os as _os
import sys as _sys

_RISK_PATH = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "services", "risk-service")
)
_app = _sys.modules.get("app")
if _app is None or _RISK_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _RISK_PATH not in _sys.path:
        _sys.path.insert(0, _RISK_PATH)

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main as risk_main
from app.main import app

client = TestClient(app)


class _MockEngine:
    """Pops a scripted response per execute() call. None → result.first()==None."""
    def __init__(self):
        self.responses: list = []

    def connect(self):
        ctx = MagicMock()
        conn = MagicMock()

        async def execute(_sql, _params=None):
            row = self.responses.pop(0) if self.responses else None
            result = MagicMock()
            result.first = MagicMock(return_value=row)
            return result

        conn.execute = execute
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx


@pytest.fixture(autouse=True)
def _stub_persist(monkeypatch):
    async def _fake_persist(req, *, approved, reason, rule, env):
        return str(uuid.uuid4())
    monkeypatch.setattr(risk_main, "_persist_decision", _fake_persist)
    yield


@pytest.fixture
def mock_engine():
    eng = _MockEngine()
    original = risk_main.engine
    risk_main.engine = eng
    yield eng
    risk_main.engine = original


def _now():
    return datetime.now(timezone.utc)


def _payload(**overrides):
    base = {
        "ticker": "AAPL", "action": "entry", "side": "buy",
        "qty": 10, "notional": 3000.0,
        "mode": "immediate", "trade_type": "paper",
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# Daily-loss baseline: missing same-day baseline → reject (default to safety)
# ══════════════════════════════════════════════════════════════════════════════


class TestDailyLossNoBaseline:
    def test_missing_baseline_rejects(self, mock_engine):
        """No same-day opening sync (baseline=None) but a current value exists →
        the loss check is unavailable, so we REJECT rather than neutralize the
        cap by treating current as the baseline."""
        mock_engine.responses = [
            (_now() - timedelta(minutes=5),),  # sync_staleness: fresh
            (_now() - timedelta(hours=1),),    # data_staleness: fresh pipeline
            None,                              # daily-loss baseline: NONE today
            (80_000.0,),                       # daily-loss current value present
        ]
        r = client.post("/check", json=_payload(action="entry"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "daily_loss_limit"
        assert "baseline" in body["reason"].lower()

    def test_no_account_value_at_all_rejects(self, mock_engine):
        """Neither baseline nor current available → broker state unknown → reject."""
        mock_engine.responses = [
            (_now() - timedelta(minutes=5),),  # sync fresh
            (_now() - timedelta(hours=1),),    # pipeline fresh
            None,                              # baseline NONE
            None,                              # current NONE
        ]
        r = client.post("/check", json=_payload(action="entry"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "daily_loss_limit"

    def test_baseline_present_and_healthy_passes(self, mock_engine):
        """Sanity: when a same-day baseline exists and loss is small, entry passes."""
        mock_engine.responses = [
            (_now() - timedelta(minutes=5),),  # sync fresh
            (_now() - timedelta(hours=1),),    # pipeline fresh
            (100_000.0,),                      # baseline today
            (99_000.0,),                       # current ~ 1% loss
            (5,),                              # pos_count
            None,                              # not held
            (100_000.0,),                      # acct for pos-pct
            None,                              # held_mv none
        ]
        r = client.post("/check", json=_payload(action="entry", notional=3000.0))
        assert r.json()["approved"] is True, r.json()


# ══════════════════════════════════════════════════════════════════════════════
# C2 — turnover counts in-flight pending sells
# ══════════════════════════════════════════════════════════════════════════════


class TestTurnoverCountsPendingSells:
    def test_pending_sell_trim_notional_counts_toward_cap(self, mock_engine, monkeypatch):
        """A prior 'pending' (recorded-but-not-yet-submitted) sell_trim must count, so a
        concurrent second sell_trim that would breach the cap is rejected. (Only
        sell_trims are capped now — exits are exempt; see test_exit_is_exempt below.)"""
        monkeypatch.setenv("MAX_DAILY_TURNOVER_PCT", "0.50")
        # sell_trims are exempt from sync_staleness + daily_loss (closing/trimming
        # always allowed), so a trim only reads the turnover rows: SUM so far, account_value.
        mock_engine.responses = [
            (45_000.0,),                       # turnover SUM so far (incl pending sell_trims)
            (100_000.0,),                      # account_value for turnover limit
        ]
        # limit = 0.5 * 100k = 50k. 45k prior + 10k this = 55k > 50k → reject.
        r = client.post("/check", json=_payload(action="sell_trim", side="sell", notional=10_000.0))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "daily_turnover_limit"

    def test_exit_is_exempt_from_turnover_cap(self, mock_engine, monkeypatch):
        """F1 policy: a full EXIT is NEVER blocked by the turnover cap — a de-risking
        close / builder-dropped rotation must always be allowed. The exit must not even
        run the turnover query, so even with the cap already breached it is approved."""
        monkeypatch.setenv("MAX_DAILY_TURNOVER_PCT", "0.50")
        # Provide turnover rows that WOULD breach the cap if they were read.
        mock_engine.responses = [
            (1_000_000.0,),                    # huge prior sell notional (would breach)
            (100_000.0,),
        ]
        r = client.post("/check", json=_payload(action="exit", side="sell", notional=50_000.0))
        body = r.json()
        assert body["approved"] is True, body
        assert body["rule_triggered"] == "ok"

    def test_turnover_sql_uses_positive_status_list_including_pending(self, mock_engine, monkeypatch):
        """The turnover query must filter on a positive status IN-list that
        includes 'pending' (in-flight sells count) — capture and assert the SQL."""
        monkeypatch.setenv("MAX_DAILY_TURNOVER_PCT", "0.50")
        captured = {"sqls": []}

        eng = mock_engine
        # ONE shared responses list across all connect() blocks (each /check uses
        # several separate `async with engine.connect()` scopes).
        responses = [
            (0.0,),                            # turnover SUM (sell_trim reads turnover rows)
            (100_000.0,),                      # account_value
        ]

        def connect():
            ctx = MagicMock()
            conn = MagicMock()

            async def execute(_sql, _params=None):
                captured["sqls"].append(str(_sql))
                row = responses.pop(0) if responses else None
                result = MagicMock()
                result.first = MagicMock(return_value=row)
                return result

            conn.execute = execute
            ctx.__aenter__ = AsyncMock(return_value=conn)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        eng.connect = connect
        r = client.post("/check", json=_payload(action="sell_trim", side="sell", notional=1_000.0))
        assert r.json()["approved"] is True
        turnover_sql = " ".join(s for s in captured["sqls"] if "sell_trim" in s).lower()
        assert "'pending'" in turnover_sql, "pending sells must count toward turnover"
        assert "'submitted'" in turnover_sql
        # positive list, not a NOT-IN exclusion
        assert "not in" not in turnover_sql
