"""Tests for the five planned safety controls now implemented in risk-service.

Each control queries the DB, so we provide a mock engine that returns rows
from a controllable script. The mock matches the asyncpg/SQLAlchemy contract
the production code uses: `engine.connect()` is an async-context-manager
yielding a connection; `conn.execute(text(...))` returns a Result with .first().
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


# ── Mock engine that returns canned rows by SQL pattern ──────────────────────


class _MockEngine:
    """Stand-in for sqlalchemy AsyncEngine.

    Configure responses by setting `engine.responses` to a list of values.
    Each `conn.execute()` pops the next response. A response of `None`
    means `result.first()` returns None.
    """
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
def mock_engine(monkeypatch):
    """Swap the module engine with a controllable mock."""
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


def _scripted_responses(*, sync_row, pl_row=None, baseline_row=None,
                       current_row=None, pos_count=None, held=None,
                       acct_row=None, held_mv=None, turnover_row=None,
                       turnover_acct_row=None, action="entry"):
    """Construct the response list in the order the production code reads.

    Order in _decide() (only the branches actually executed for the action):
      sync_staleness:       sync_row (always for buys+sells)
      data_staleness:       pl_row   (buys only — entry, buy_add)
      daily_loss_limit:     baseline_row, current_row
      max_positions_limit:  pos_count, held  (entry only)
      max_position_pct_limit: acct_row, held_mv  (buys only — entry, buy_add)
      daily_turnover_limit: turnover_row, turnover_acct_row  (sells only — exit, sell_trim)
    """
    # Exits / sell_trims are EXEMPT from sync_staleness + daily_loss (closing must
    # always be allowed), so a close only reads the turnover rows.
    if action in ("exit", "sell_trim"):
        return [turnover_row, turnover_acct_row]
    rows = [sync_row]
    if action in ("entry", "buy_add"):
        rows.append(pl_row)
    rows.append(baseline_row)
    rows.append(current_row)
    if action == "entry":
        rows.append(pos_count)
        rows.append(held)
    if action in ("entry", "buy_add"):
        rows.append(acct_row)
        rows.append(held_mv)
    return rows


# ── Defaults that always pass each gate ─────────────────────────────────────


_OK = {
    "sync_row":   (_now() - timedelta(minutes=10),),   # fresh sync
    "pl_row":     (_now() - timedelta(hours=1),),       # fresh pipeline
    "baseline_row": (100_000.0,),                       # start-of-day = $100k
    "current_row":  (99_500.0,),                        # current ≈ baseline (0.5% loss, fine)
    "pos_count":  (5,),                                 # 5 live positions
    "held":       None,                                 # ticker not already held
    "acct_row":   (100_000.0,),
    "held_mv":    None,                                 # ticker has no existing position
}


def _ok_responses(action="entry", overrides=None):
    rows = _scripted_responses(action=action, **{**_OK, **(overrides or {})})
    return rows


# ═════════════════════════════════════════════════════════════════════════════
# 1. sync_staleness — refuse ALL actions on stale alpaca-sync
# ═════════════════════════════════════════════════════════════════════════════


class TestSyncStaleness:
    def test_no_successful_sync_blocks_entry(self, mock_engine):
        mock_engine.responses = [None]  # sync row missing
        r = client.post("/check", json=_payload(action="entry"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "sync_staleness"
        assert "no successful alpaca-sync" in body["reason"].lower()

    def test_stale_sync_does_not_block_exit(self, mock_engine):
        # Closing must always be allowed — a stale broker sync never blocks an exit.
        # The exit doesn't even run the sync-age query; it only reads turnover rows.
        mock_engine.responses = [(0.0,), (100_000.0,)]  # turnover SUM, account_value
        r = client.post("/check", json=_payload(action="exit", side="sell", notional=2000.0))
        body = r.json()
        assert body["approved"] is True, body
        assert body["rule_triggered"] == "ok"

    def test_fresh_sync_does_not_block(self, mock_engine):
        # Use action=exit so we skip buy-only checks; still need turnover rows
        mock_engine.responses = _ok_responses(action="exit", overrides={
            "turnover_row":      (0.0,),    # no sells today
            "turnover_acct_row": (100_000.0,),
        })
        r = client.post("/check", json=_payload(action="exit", side="sell", notional=2000.0))
        body = r.json()
        assert body["approved"] is True, body


# ═════════════════════════════════════════════════════════════════════════════
# 2. data_staleness — refuse buys when pipeline rankings are too old
# ═════════════════════════════════════════════════════════════════════════════


class TestDataStaleness:
    def test_no_pipeline_run_blocks_entry(self, mock_engine):
        # sync ok, then pl_row=None
        mock_engine.responses = [_OK["sync_row"], None]
        r = client.post("/check", json=_payload(action="entry"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "data_staleness"
        assert "no successful pipeline" in body["reason"].lower()

    def test_old_pipeline_blocks_buy_add(self, mock_engine):
        mock_engine.responses = [
            _OK["sync_row"],
            (_now() - timedelta(hours=120),),  # pipeline 5 days old
        ]
        r = client.post("/check", json=_payload(action="buy_add"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "data_staleness"

    def test_stale_pipeline_does_not_block_exit(self, mock_engine):
        # Exits are not gated by data staleness — they only need fresh broker state.
        mock_engine.responses = _ok_responses(action="exit", overrides={
            "turnover_row":      (0.0,),
            "turnover_acct_row": (100_000.0,),
        })
        # Even if pipeline was stale, exits would still pass — but we won't
        # query pl_row for an exit, so a sync_ok mock is enough.
        r = client.post("/check", json=_payload(action="exit", side="sell"))
        assert r.json()["approved"] is True


# ═════════════════════════════════════════════════════════════════════════════
# 3. daily_loss_limit — refuse ALL actions when down > MAX_DAILY_LOSS_PCT
# ═════════════════════════════════════════════════════════════════════════════


class TestDailyLossLimit:
    def test_loss_above_threshold_blocks_entry(self, mock_engine):
        # baseline $100k, current $80k = 20% loss > 10% default cap
        mock_engine.responses = [
            _OK["sync_row"],
            _OK["pl_row"],
            (100_000.0,),  # baseline
            (80_000.0,),   # current
        ]
        r = client.post("/check", json=_payload(action="entry"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "daily_loss_limit"
        assert "20" in body["reason"]

    def test_loss_below_threshold_passes(self, mock_engine):
        mock_engine.responses = _ok_responses(action="entry", overrides={
            "baseline_row": (100_000.0,),
            "current_row":  (95_000.0,),  # 5% loss < 10% cap
        })
        r = client.post("/check", json=_payload(action="entry"))
        assert r.json()["approved"] is True

    def test_loss_limit_does_not_block_exit(self, mock_engine):
        # Daily-loss halts OPENING risk only. A close/trim must ALWAYS be allowed —
        # on a meltdown day you must still be able to de-risk — so an exit is approved
        # even at a 50% drawdown (the exit doesn't run the daily-loss query at all).
        mock_engine.responses = [(0.0,), (50_000.0,)]  # turnover SUM, account_value
        r = client.post("/check", json=_payload(action="exit", side="sell", notional=2000.0))
        body = r.json()
        assert body["approved"] is True, body
        assert body["rule_triggered"] == "ok"


# ═════════════════════════════════════════════════════════════════════════════
# 4. max_positions_limit — refuse new entries past the cap
# ═════════════════════════════════════════════════════════════════════════════


class TestMaxPositionsLimit:
    def test_at_capacity_new_entry_blocked(self, mock_engine):
        mock_engine.responses = [
            _OK["sync_row"],
            _OK["pl_row"],
            _OK["baseline_row"],
            _OK["current_row"],
            (35,),    # at cap
            None,     # ticker NOT already held
        ]
        r = client.post("/check", json=_payload(action="entry", ticker="NEWC"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "max_positions_limit"
        assert "35" in body["reason"]

    def test_at_capacity_but_already_held_passes(self, mock_engine):
        # Re-entering an already-held ticker is somewhat weird but shouldn't
        # be blocked by count cap — we'd skip the count gate and continue.
        # Sequence: sync, pl, baseline, current, pos_count=35, held=(1,),
        # then continue to position pct check → acct, held_mv.
        mock_engine.responses = [
            _OK["sync_row"],
            _OK["pl_row"],
            _OK["baseline_row"],
            _OK["current_row"],
            (35,),         # at cap
            (1,),          # already held → skip
            _OK["acct_row"],
            (3_000.0,),    # existing position $3k
        ]
        r = client.post("/check", json=_payload(action="entry"))
        assert r.json()["approved"] is True

    def test_below_capacity_passes(self, mock_engine):
        mock_engine.responses = _ok_responses(action="entry", overrides={
            "pos_count": (10,),
        })
        r = client.post("/check", json=_payload(action="entry", ticker="ABCD"))
        assert r.json()["approved"] is True

    def test_buy_add_not_blocked_by_count(self, mock_engine):
        # buy_add doesn't grow the portfolio count, so it skips the
        # max_positions check entirely.
        mock_engine.responses = _ok_responses(action="buy_add", overrides={
            # No pos_count/held rows needed for buy_add
        })
        # buy_add skips the count check; remove those two rows from script
        # Note: _ok_responses for buy_add does NOT include pos_count/held
        rows = [_OK["sync_row"], _OK["pl_row"], _OK["baseline_row"], _OK["current_row"],
                _OK["acct_row"], None]
        mock_engine.responses = rows
        r = client.post("/check", json=_payload(action="buy_add"))
        assert r.json()["approved"] is True

    def test_rotation_projected_count_passes(self, mock_engine):
        # Full-rotation regression (2026-06-16): the broker holds 42 names but the
        # cycle queues 34 exits, so the PROJECTED post-open book is 42-34+entries.
        # The gate now reads that projected scalar from SQL (not the raw 42), so
        # pos_count here is the already-netted 8 → well under the cap 35 → passes.
        # Before the netting fix the gate saw 42 >= 35 and rejected every entry,
        # self-wedging the rotation.
        mock_engine.responses = [
            _OK["sync_row"],
            _OK["pl_row"],
            _OK["baseline_row"],
            _OK["current_row"],
            (8,),     # projected = 42 held - 34 queued exits + 0 entries so far
            None,     # ticker NOT already held
            _OK["acct_row"],
            None,
        ]
        r = client.post("/check", json=_payload(action="entry", ticker="NVDA"))
        assert r.json()["approved"] is True

    def test_negative_projection_clamps_to_zero(self, mock_engine):
        # If a sync lag makes queued exits exceed the snapshot's held count, the
        # netted scalar can go negative; it must clamp to 0 (plenty of room), never
        # wrap or confuse the cap comparison.
        mock_engine.responses = [
            _OK["sync_row"],
            _OK["pl_row"],
            _OK["baseline_row"],
            _OK["current_row"],
            (-3,),    # netted projection went negative
            None,     # ticker NOT already held
            _OK["acct_row"],
            None,
        ]
        r = client.post("/check", json=_payload(action="entry", ticker="NVDA"))
        assert r.json()["approved"] is True

    def test_query_nets_queued_exits_with_deferred(self):
        # Source-shape guard: the MAX_POSITIONS query MUST subtract held names with
        # a queued `exit` order, and that netting MUST match the 'deferred' status —
        # the after-close cron approves exits first (flipping them to 'deferred')
        # BEFORE entries are risk-checked. Dropping either is the rotation-wedge
        # regression, so fail loudly if a refactor removes them.
        import inspect
        src = inspect.getsource(risk_main._decide)
        assert "deferred" in risk_main._OPEN_STATUS_SQL
        # the exit-subtraction clause: an action='exit' membership test against the
        # held tickers, combined via subtraction into the projected count.
        assert "action = 'exit'" in src
        assert "_OPEN_STATUS_SQL" in src
        # subtraction of the exiting-held term must be present (not just additions)
        assert "- " in src or "-\n" in src


# ═════════════════════════════════════════════════════════════════════════════
# 5. max_position_pct_limit — refuse buys that push a ticker above the cap
# ═════════════════════════════════════════════════════════════════════════════


class TestMaxPositionPctLimit:
    def test_concentrated_position_blocks_buy_add(self, mock_engine):
        # Existing $14k position + $3k buy_add = $17k / $100k = 17% > 15% cap
        mock_engine.responses = [
            _OK["sync_row"],
            _OK["pl_row"],
            _OK["baseline_row"],
            _OK["current_row"],
            # buy_add skips count check
            (100_000.0,),     # account_value
            (14_000.0,),      # current_mv
        ]
        r = client.post("/check", json=_payload(action="buy_add", notional=3000.0))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "max_position_pct_limit"
        assert "17" in body["reason"]

    def test_within_limit_passes(self, mock_engine):
        # $3k notional / $100k account = 3% (well under 15%)
        mock_engine.responses = _ok_responses(action="entry", overrides={
            "acct_row": (100_000.0,),
            "held_mv": None,
        })
        r = client.post("/check", json=_payload(action="entry", notional=3000.0))
        assert r.json()["approved"] is True

    def test_does_not_apply_to_sells(self, mock_engine):
        # Sells reduce position size, so the cap is irrelevant. The check is
        # skipped for action in ('exit','sell_trim').
        mock_engine.responses = _ok_responses(action="exit", overrides={
            "turnover_row":      (0.0,),
            "turnover_acct_row": (100_000.0,),
        })
        r = client.post("/check", json=_payload(action="exit", side="sell"))
        assert r.json()["approved"] is True


# ═════════════════════════════════════════════════════════════════════════════
# Cross-cutting: env-var disable, DB exception degrades safely
# ═════════════════════════════════════════════════════════════════════════════


class TestControlDisablement:
    def test_max_position_pct_disabled_with_one(self, mock_engine, monkeypatch):
        """MAX_POSITION_PCT >= 1.0 disables the cap (entire portfolio allowed)."""
        monkeypatch.setenv("MAX_POSITION_PCT", "1.0")
        # Production code's branch: max_pos_pct > 0 and max_pos_pct < 1.0
        # so 1.0 should be excluded from the gate. With cap disabled we don't
        # query acct/held_mv, so the response script drops those rows.
        rows = [
            _OK["sync_row"],
            _OK["pl_row"],
            _OK["baseline_row"],
            _OK["current_row"],
            (10,),     # pos_count
            None,      # not held
        ]
        # No acct_row, no held_mv since pct check is disabled
        mock_engine.responses = rows
        r = client.post("/check", json=_payload(action="entry"))
        assert r.json()["approved"] is True

    def test_db_exception_fails_closed(self, mock_engine, monkeypatch):
        """If a safety-critical DB query throws, the trade is REJECTED (fail-closed).

        A DB error means we cannot evaluate sync-staleness / daily-loss /
        max-positions / position-pct, so we default to safety and reject rather
        than approving by default. (Previously this fail-OPEN'd to approved.)
        """
        # Replace execute with a raiser
        async def _raise(*_a, **_k):
            raise RuntimeError("simulated DB outage")

        bad_conn = MagicMock()
        bad_conn.execute = _raise
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=bad_conn)
        ctx.__aexit__ = AsyncMock(return_value=None)
        mock_engine.connect = lambda: ctx

        r = client.post("/check", json=_payload(action="entry"))
        body = r.json()
        assert body["approved"] is False
        assert body["rule_triggered"] == "control_unavailable"


# ═════════════════════════════════════════════════════════════════════════════
# /health exposes the new controls
# ═════════════════════════════════════════════════════════════════════════════


def test_health_exposes_new_controls():
    body = client.get("/health").json()
    for key in (
        "max_daily_loss_pct",
        "max_position_pct",
        "max_positions",
        "max_data_age_hours",
        "max_sync_age_hours",
    ):
        assert key in body, f"missing {key} in /health"
