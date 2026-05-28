"""Integration tests for Alpaca trading scenarios.

Runs against the live Docker stack (postgres:5433, trade-executor:8012,
risk-service:8011).  Each test seeds DB state via psql, calls the
trade-executor API, verifies the response *and* DB state, then cleans up.

Skip the whole module if the stack is not reachable:
    pytest tests/trade_executor/test_alpaca_scenarios.py -v
"""
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

# ── Config ────────────────────────────────────────────────────────────────────

TE_URL = "http://localhost:8012"
PSQL = [
    "docker", "exec", "stocker-postgres-1",
    "psql", "-U", "stocker", "-d", "stocker",
]
RISK_CONTAINER = "stocker-risk-service-1"


def _stack_up() -> bool:
    try:
        r = requests.get(f"{TE_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _trade_executor_has_credentials() -> bool:
    """Return True if the live trade-executor was launched with Alpaca creds.

    The harness overlay (tests/harness/docker-compose.yml) wires
    ALPACA_API_KEY=harness-test-key into trade-executor so it can submit to
    alpaca-sim. In that mode, the no-credentials tests in this module cannot
    pass: the trade-executor will actually attempt an HTTP POST to alpaca-sim
    instead of short-circuiting with a credential error.
    """
    try:
        r = requests.get(f"{TE_URL}/health", timeout=3)
        return bool(r.json().get("has_credentials"))
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _stack_up(), reason="Docker stack not reachable on :8012"
)

_NO_CRED_SKIP = pytest.mark.skipif(
    _trade_executor_has_credentials(),
    reason=(
        "trade-executor has Alpaca credentials (running under harness overlay) — "
        "skip the no-credentials path tests; alpaca-sim returns 500 for unknown "
        "tickers instead of a clean 'credential' error"
    ),
)


# ── DB helpers ────────────────────────────────────────────────────────────────

def psql(sql: str) -> str:
    result = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed:\n{result.stderr}\nSQL: {sql}")
    return result.stdout


def psql_val(sql: str) -> str:
    result = subprocess.run(
        PSQL + ["-t", "-c", sql], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql failed:\n{result.stderr}")
    return result.stdout.strip()


def new_id() -> str:
    return str(uuid.uuid4())


def seed_delta_run(strategy_id: str = "inttest") -> str:
    run_id = new_id()
    today = datetime.now().strftime("%Y-%m-%d")
    psql(
        f"INSERT INTO delta_runs (run_id, strategy_id, status, run_date, triggered_by) "
        f"VALUES ('{run_id}', '{strategy_id}', 'success', '{today}', 'test')"
    )
    return run_id


def seed_delta_intent(
    run_id: str,
    ticker: str,
    action: str,
    weight: float = 0.05,
    actual_weight: float = None,
) -> str:
    intent_id = new_id()
    w = str(weight) if weight is not None else "NULL"
    aw = str(actual_weight) if actual_weight is not None else "NULL"
    psql(
        f"INSERT INTO delta_intents (id, run_id, ticker, action, current_weight, actual_weight) "
        f"VALUES ('{intent_id}', '{run_id}', '{ticker}', '{action}', {w}, {aw})"
    )
    return intent_id


def seed_sync_run(
    account_value: float = 100_000.0,
    age_hours: float = 0.0,
    buying_power: float | None = None,
) -> str:
    run_id = new_id()
    completed_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    bp = buying_power if buying_power is not None else account_value
    psql(
        f"INSERT INTO alpaca_sync_runs (run_id, status, account_value, buying_power, completed_at) "
        f"VALUES ('{run_id}', 'success', {account_value}, {bp}, '{completed_at}')"
    )
    return run_id


def seed_live_position(sync_run_id: str, ticker: str, qty: float, price: float) -> None:
    psql(
        f"INSERT INTO live_positions (sync_run_id, ticker, qty, current_price) "
        f"VALUES ('{sync_run_id}', '{ticker}', {qty}, {price})"
    )


def seed_daily_price(ticker: str, close: float) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    psql(
        f"INSERT INTO daily_prices (ticker, date, close) "
        f"VALUES ('{ticker}', '{today}', {close}) "
        f"ON CONFLICT (ticker, date) DO UPDATE SET close = EXCLUDED.close"
    )


def seed_alpaca_order(intent_id: str, ticker: str, status: str = "pending") -> str:
    order_id = new_id()
    psql(
        f"INSERT INTO alpaca_orders (id, intent_id, ticker, action, side, status) "
        f"VALUES ('{order_id}', '{intent_id}', '{ticker}', 'entry', 'buy', '{status}')"
    )
    return order_id


def cleanup_run(run_id: str) -> None:
    psql(f"DELETE FROM delta_runs WHERE run_id = '{run_id}'")


def cleanup_sync_run(sync_run_id: str) -> None:
    psql(f"DELETE FROM alpaca_sync_runs WHERE run_id = '{sync_run_id}'")


def purge_successful_sync_runs() -> list[str]:
    """Delete all current successful sync runs; return their IDs so they can be analysed."""
    ids_raw = psql_val(
        "SELECT string_agg(run_id::text, ',') FROM alpaca_sync_runs WHERE status='success'"
    )
    psql("DELETE FROM alpaca_sync_runs WHERE status='success'")
    return [i for i in (ids_raw or "").split(",") if i]


def cleanup_orders_by_ticker(ticker: str) -> None:
    psql(f"DELETE FROM alpaca_orders WHERE ticker = '{ticker}'")


def cleanup_daily_price(ticker: str) -> None:
    psql(f"DELETE FROM daily_prices WHERE ticker = '{ticker}'")


def get_order_row(intent_id: str) -> dict:
    """Return the most recent alpaca_orders row for an intent as {status, error_message}."""
    raw = psql_val(
        f"SELECT status || '||' || COALESCE(risk_approved::text, 'NULL') || '||' "
        f"       || COALESCE(error_message, '') "
        f"FROM alpaca_orders WHERE intent_id = '{intent_id}' "
        f"ORDER BY created_at DESC LIMIT 1"
    )
    if not raw:
        return {}
    parts = raw.split("||", 2)
    return {
        "status": parts[0] if len(parts) > 0 else "",
        "risk_approved": parts[1] if len(parts) > 1 else "",
        "error_message": parts[2] if len(parts) > 2 else "",
    }


def submit(intent_id: str, mode: str = "immediate") -> requests.Response:
    return requests.post(
        f"{TE_URL}/jobs/submit",
        json={"intent_id": intent_id, "mode": mode},
        timeout=30,
    )


def enable_kill_switch() -> None:
    subprocess.run(
        ["docker", "exec", RISK_CONTAINER, "touch", "/tmp/kill_switch"],
        check=True, timeout=5
    )


def disable_kill_switch() -> None:
    subprocess.run(
        ["docker", "exec", RISK_CONTAINER, "sh", "-c", "rm -f /tmp/kill_switch"],
        check=True, timeout=5
    )


# ── Test: kill switch ─────────────────────────────────────────────────────────

class TestKillSwitch:
    TICKER = "TKSW1"

    def test_kill_switch_rejects_entry(self):
        """Active kill switch → risk_rejected; DB row persisted with risk_approved=false."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 100.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.05)
        enable_kill_switch()
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "risk_rejected", data
            reason = (data.get("risk_reason") or data.get("reason") or "").lower()
            assert "kill" in reason, f"Expected 'kill' in reason: {reason}"
            db = get_order_row(intent_id)
            assert db["status"] == "risk_rejected"
            assert db["risk_approved"] == "false"
        finally:
            disable_kill_switch()
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: notional limit ──────────────────────────────────────────────────────

class TestNotionalLimit:
    TICKER = "TNOT1"

    def test_notional_exceeds_50k_limit_rejects(self):
        """Notional > $50k limit triggers risk_rejected.

        Account=$2M, weight=10%, price=$5 → qty=40000, notional=$200k > $50k.
        """
        sync_id = seed_sync_run(2_000_000.0)
        seed_daily_price(self.TICKER, 5.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.10)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "risk_rejected", data
            reason = (data.get("risk_reason") or data.get("reason") or "").lower()
            assert "notional" in reason, f"Expected 'notional' in reason: {reason}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)

    def test_notional_within_limit_passes_risk(self):
        """Notional < $50k passes risk (fails later at Alpaca — no creds)."""
        # account=$100k, weight=2%, price=$100 → qty=20, notional=$2k < $50k
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 100.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            # Passes risk → fails at Alpaca (no credentials)
            assert data["status"] == "failed", data
            assert data["risk_approved"] is True
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: no Alpaca credentials ───────────────────────────────────────────────

@_NO_CRED_SKIP
class TestNoCredentials:
    TICKER_ENTRY = "TNCR1"
    TICKER_EXIT = "TNCR2"

    def test_entry_passes_risk_fails_at_alpaca(self):
        """Entry: risk approved, no creds → status='failed', order persisted."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER_ENTRY, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER_ENTRY, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "failed", data
            assert data["risk_approved"] is True
            assert data["qty"] == pytest.approx(40.0)   # floor(100k*0.02/50)
            assert data["notional"] == pytest.approx(2000.0)
            reason = (data.get("reason") or "").lower()
            assert "credential" in reason or "ssl" in reason or "certificate" in reason, data
            db = get_order_row(intent_id)
            assert db["status"] == "failed"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER_ENTRY)

    def test_exit_passes_risk_fails_at_alpaca(self):
        """Exit: sized from live_positions, risk approved, no creds → failed."""
        sync_id = seed_sync_run(100_000.0)
        seed_live_position(sync_id, self.TICKER_EXIT, qty=25.0, price=200.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER_EXIT, "exit")
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "failed", data
            assert data["risk_approved"] is True
            assert data["side"] == "sell"
            assert data["qty"] == pytest.approx(25.0)
            assert data["notional"] == pytest.approx(5000.0)
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)


# ── Test: exit with no live position ─────────────────────────────────────────

class TestExitNoPosition:
    TICKER = "TENP1"

    def test_exit_missing_position_returns_400(self):
        """Exit aborted when no live position exists for the ticker."""
        sync_id = seed_sync_run(100_000.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "exit")
        try:
            r = submit(intent_id)
            assert r.status_code == 400
            assert "no live position" in r.json()["detail"].lower(), r.json()
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)


# ── Test: stale sync (exit) ───────────────────────────────────────────────────

class TestStaleSyncExit:
    TICKER = "TSSE1"

    def test_exit_stale_sync_returns_409(self):
        """Exit refused when alpaca-sync completed_at is > 24h old.

        Purges any competing fresh sync runs first so size_exit cannot pick
        up a newer successful sync from another test.
        """
        purge_successful_sync_runs()
        sync_id = seed_sync_run(100_000.0, age_hours=48.0)
        seed_live_position(sync_id, self.TICKER, qty=30.0, price=100.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "exit")
        try:
            r = submit(intent_id)
            assert r.status_code == 409
            detail = r.json()["detail"].lower()
            assert "alpaca-sync" in detail or "sync" in detail, r.json()
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)


# ── Test: stale sync (entry) ──────────────────────────────────────────────────

class TestStaleSyncEntry:
    TICKER = "TSES1"

    def test_entry_stale_sync_returns_409(self):
        """Entry refused when the most-recent alpaca-sync account data is > 24h old.

        Purges any competing fresh sync runs before seeding the stale one so
        the size_order step cannot pick up a newer successful run from other tests.
        """
        purge_successful_sync_runs()
        sync_id = seed_sync_run(100_000.0, age_hours=48.0)
        seed_daily_price(self.TICKER, 100.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            assert r.status_code == 409
            detail = r.json()["detail"].lower()
            assert "alpaca-sync" in detail or "sync" in detail, r.json()
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: entry qty rounds to zero ────────────────────────────────────────────

class TestEntryQtyZero:
    TICKER = "TEQZ1"

    def test_qty_rounds_to_zero_returns_400(self):
        """Entry refused when floor(notional / price) < 1 share.

        account=$1 000, weight=5% → notional=$50, price=$500 → qty=0.
        """
        sync_id = seed_sync_run(1_000.0)
        seed_daily_price(self.TICKER, 500.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            assert r.status_code == 400
            assert "too small" in r.json()["detail"].lower(), r.json()
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: idempotency ─────────────────────────────────────────────────────────

class TestIdempotency:
    TICKER = "TIDEM1"

    def test_pending_order_blocks_second_submit(self):
        """Second submit for intent with existing pending order → duplicate."""
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.03)
        seed_alpaca_order(intent_id, self.TICKER, status="pending")
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            assert r.json()["status"] == "duplicate", r.json()
        finally:
            cleanup_orders_by_ticker(self.TICKER)
            cleanup_run(run_id)

    def test_submitted_order_blocks_second_submit(self):
        """Second submit for intent with existing submitted order → duplicate."""
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.03)
        seed_alpaca_order(intent_id, self.TICKER, status="submitted")
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            assert r.json()["status"] == "duplicate", r.json()
        finally:
            cleanup_orders_by_ticker(self.TICKER)
            cleanup_run(run_id)

    def test_risk_rejected_order_blocks_resubmit(self):
        """Existing risk_rejected order also triggers duplicate (intent is settled)."""
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.03)
        seed_alpaca_order(intent_id, self.TICKER, status="risk_rejected")
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            assert r.json()["status"] == "duplicate", r.json()
        finally:
            cleanup_orders_by_ticker(self.TICKER)
            cleanup_run(run_id)

    def test_failed_order_allows_retry(self):
        """Existing failed order does NOT block a retry — proceeds to Alpaca step."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.02)
        seed_alpaca_order(intent_id, self.TICKER, status="failed")
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            # No credentials → fails at Alpaca (not idempotency)
            data = r.json()
            assert data["status"] in ("failed", "risk_rejected"), data
            assert data["status"] != "duplicate", "Failed order should not block retry"
        finally:
            cleanup_orders_by_ticker(self.TICKER)
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: buy_add drift too small ─────────────────────────────────────────────

class TestBuyAddDriftTooSmall:
    TICKER = "TBAD1"

    def test_drift_rounds_to_zero_returns_400(self):
        """buy_add refused when drift notional < one-share price.

        account=$100k, current_weight=10%, actual_weight=9.9%, price=$50k
        → drift=0.1% × $100k = $100, qty=floor($100/$50k)=0 → 400.
        """
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 50_000.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(
            run_id, self.TICKER, "buy_add",
            weight=0.10, actual_weight=0.099,
        )
        try:
            r = submit(intent_id)
            assert r.status_code == 400
            detail = r.json()["detail"].lower()
            assert "drift too small" in detail or "too small" in detail, r.json()
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: sell_trim ───────────────────────────────────────────────────────────

class TestSellTrim:
    TICKER = "TSTM1"

    def test_sell_trim_sizes_from_drift_fails_at_alpaca(self):
        """sell_trim: (actual-target)×account/price shares, risk passes, no creds → failed.

        actual_weight=12%, target_weight=10%, price=$100, account=$100k
        → drift=0.12-0.10=0.01999… (float) × $100k = $1999.99 → qty=19 shares.
        """
        sync_id = seed_sync_run(100_000.0)
        seed_live_position(sync_id, self.TICKER, qty=120.0, price=100.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(
            run_id, self.TICKER, "sell_trim",
            weight=0.10, actual_weight=0.12,
        )
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "failed", data
            assert data["risk_approved"] is True
            assert data["side"] == "sell"
            assert data["qty"] == pytest.approx(19.0)    # float: floor(1999.99.../100)
            assert data["notional"] == pytest.approx(1900.0)
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)


# ── Test: partial fill display ────────────────────────────────────────────────

class TestPartialFillDisplay:
    def test_partial_fill_visible_in_orders_recent(self):
        """Seed a partially-filled order; verify it appears in /orders/recent."""
        order_id = new_id()
        psql(
            f"INSERT INTO alpaca_orders "
            f"(id, ticker, action, side, qty, notional, status, mode, risk_approved, "
            f" alpaca_status, filled_qty, avg_fill_price) "
            f"VALUES ('{order_id}', 'PLTR', 'entry', 'buy', 100.0, 1000.0, 'submitted', "
            f"'immediate', true, 'partially_filled', 50.0, 9.95)"
        )
        try:
            r = requests.get(f"{TE_URL}/orders/recent", timeout=10)
            assert r.status_code == 200
            orders = r.json()
            match = next((o for o in orders if o["id"] == order_id), None)
            assert match is not None, "Partial fill order not found in /orders/recent"
            assert match["filled_qty"] == pytest.approx(50.0)
            assert match["avg_fill_price"] == pytest.approx(9.95)
            assert match["alpaca_status"] == "partially_filled"
        finally:
            psql(f"DELETE FROM alpaca_orders WHERE id = '{order_id}'")

    def test_filled_order_visible_in_orders_recent(self):
        """Seed a filled order; verify filled_at and avg_fill_price are returned."""
        order_id = new_id()
        filled_at = datetime.now(timezone.utc).isoformat()
        psql(
            f"INSERT INTO alpaca_orders "
            f"(id, ticker, action, side, qty, notional, status, mode, risk_approved, "
            f" alpaca_status, filled_qty, avg_fill_price, filled_at) "
            f"VALUES ('{order_id}', 'NVDA', 'entry', 'buy', 10.0, 8000.0, 'submitted', "
            f"'immediate', true, 'filled', 10.0, 800.12, '{filled_at}')"
        )
        try:
            r = requests.get(f"{TE_URL}/orders/recent", timeout=10)
            assert r.status_code == 200
            match = next((o for o in r.json() if o["id"] == order_id), None)
            assert match is not None
            assert match["filled_qty"] == pytest.approx(10.0)
            assert match["avg_fill_price"] == pytest.approx(800.12)
            assert match["alpaca_status"] == "filled"
            assert match["filled_at"] is not None
        finally:
            psql(f"DELETE FROM alpaca_orders WHERE id = '{order_id}'")


# ── Test: invalid intents ─────────────────────────────────────────────────────

class TestInvalidIntents:
    def test_nonexistent_intent_returns_404(self):
        """A random UUID that doesn't exist in delta_intents → 404."""
        r = submit(new_id())
        assert r.status_code == 404

    def test_hold_action_not_tradeable_returns_400(self):
        """'hold' is not in the tradeable actions set — rejected with 400."""
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, "TXOM1", "hold")
        try:
            r = submit(intent_id)
            assert r.status_code == 400
            assert "not tradeable" in r.json()["detail"].lower(), r.json()
        finally:
            cleanup_run(run_id)

    def test_watch_action_not_tradeable_returns_400(self):
        """'watch' is not in the tradeable actions set — rejected with 400."""
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, "TXOM2", "watch")
        try:
            r = submit(intent_id)
            assert r.status_code == 400
            assert "not tradeable" in r.json()["detail"].lower(), r.json()
        finally:
            cleanup_run(run_id)

    def test_invalid_uuid_returns_400(self):
        """Non-UUID intent_id is rejected before any DB query."""
        r = requests.post(
            f"{TE_URL}/jobs/submit",
            json={"intent_id": "not-a-uuid", "mode": "immediate"},
            timeout=10,
        )
        assert r.status_code == 400
        assert "UUID" in r.json()["detail"]


# ── Test: audit trail ─────────────────────────────────────────────────────────

class TestAuditTrail:
    TICKER = "TADT1"

    def test_every_submit_creates_execution_trace(self):
        """Successful (risk-approved) submissions include trace_id in the response."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 10.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            trace_id = data.get("trace_id")
            assert trace_id is not None, "trace_id missing from response"
            count = psql_val(
                f"SELECT COUNT(*) FROM execution_traces WHERE trace_id = '{trace_id}'"
            )
            assert count == "1", f"Expected 1 execution_trace row, got {count}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)

    def test_risk_rejected_order_persisted_with_audit(self):
        """risk_rejected flow writes alpaca_orders row with risk_approved=false."""
        enable_kill_switch()
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 40.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            assert r.json()["status"] == "risk_rejected"
            db = get_order_row(intent_id)
            assert db["status"] == "risk_rejected"
            assert db["risk_approved"] == "false"
        finally:
            disable_kill_switch()
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)

    @_NO_CRED_SKIP
    def test_failed_order_has_error_message_in_db(self):
        """Failed order (no Alpaca creds) has a meaningful error_message column."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 10.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.json()["status"] == "failed"
            db = get_order_row(intent_id)
            err = db["error_message"].lower()
            assert "credential" in err or "ssl" in err or "certificate" in err, db
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)

    def test_execution_steps_logged_per_stage(self):
        """Each successful submit produces at least one execution_steps row for the trace."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 10.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            trace_id = r.json().get("trace_id")
            assert trace_id is not None
            count = psql_val(
                f"SELECT COUNT(*) FROM execution_steps WHERE trace_id = '{trace_id}'"
            )
            assert int(count) >= 1, f"Expected >= 1 execution_steps row, got {count}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: order time_in_force ─────────────────────────────────────────────────

class TestScheduledMode:
    TICKER = "TSCH1"

    def test_scheduled_mode_creates_day_order(self):
        """mode='scheduled' produces time_in_force='day' in alpaca_orders."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.02)
        try:
            r = submit(intent_id, mode="scheduled")
            assert r.status_code == 200
            data = r.json()
            # Passes risk → fails at Alpaca (no creds)
            assert data["status"] == "failed"
            tif = psql_val(
                f"SELECT time_in_force FROM alpaca_orders "
                f"WHERE intent_id = '{intent_id}' ORDER BY created_at DESC LIMIT 1"
            )
            assert tif == "day", f"Expected day, got '{tif}'"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)

    def test_immediate_mode_also_creates_day_order(self):
        """Both modes route through time_in_force='day'. The mode field is
        preserved in alpaca_orders.mode for audit."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER, "entry", weight=0.02)
        try:
            r = submit(intent_id, mode="immediate")
            assert r.status_code == 200
            tif = psql_val(
                f"SELECT time_in_force FROM alpaca_orders "
                f"WHERE intent_id = '{intent_id}' ORDER BY created_at DESC LIMIT 1"
            )
            assert tif == "day", f"Expected day, got '{tif}'"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)


# ── Test: entry price fallback ────────────────────────────────────────────────

class TestEntryPriceFallback:
    TICKER_LIVE = "TEPF1"
    TICKER_DAILY = "TEPF2"

    def test_entry_uses_live_position_price(self):
        """Entry prefers current_price from live_positions over daily_prices."""
        sync_id = seed_sync_run(100_000.0)
        seed_live_position(sync_id, self.TICKER_LIVE, qty=0.0, price=200.0)
        seed_daily_price(self.TICKER_LIVE, 100.0)   # stale — should be ignored
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER_LIVE, "entry", weight=0.04)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            # 100k × 4% / $200 = 20 shares (not 40 from $100 price)
            assert data["qty"] == pytest.approx(20.0), f"Wrong qty: {data['qty']}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER_LIVE)

    def test_entry_falls_back_to_daily_price(self):
        """Entry falls back to daily_prices.close when no live_positions row."""
        sync_id = seed_sync_run(100_000.0)
        seed_daily_price(self.TICKER_DAILY, 250.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, self.TICKER_DAILY, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            # 100k × 5% / $250 = 20 shares
            assert data["qty"] == pytest.approx(20.0), f"Wrong qty: {data['qty']}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER_DAILY)


# ── Test: already-held guard ──────────────────────────────────────────────────

try:
    from app.main import EXIT_SYNC_MAX_AGE_HOURS as _EXIT_SYNC_MAX_AGE_HOURS
except ImportError:
    _EXIT_SYNC_MAX_AGE_HOURS = 24


class TestAlreadyHeldGuard:
    """Integration tests for the already-held guard in the trade-executor.

    The guard blocks entry intents when the broker already holds the ticker,
    preventing duplicate buy orders caused by a delta run firing before
    alpaca-sync captures the fill.
    """

    def test_entry_blocked_when_ticker_already_held(self):
        """Entry blocked when ticker is held at the broker (qty > 0 in latest sync)."""
        ticker = "AHG1"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        seed_live_position(sync_id, ticker, qty=100.0, price=50.0)
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "failed", data
            reason = (data.get("reason") or data.get("risk_reason") or "").lower()
            assert "already held" in reason, f"Expected 'already held' in reason: {reason}"
            # alpaca_orders row
            db = get_order_row(intent_id)
            assert db["status"] == "failed", db
            # execution_steps row for already_held_check
            trace_id = data["trace_id"]
            step_status = psql_val(
                f"SELECT status FROM execution_steps "
                f"WHERE trace_id = '{trace_id}' AND step_name = 'already_held_check' LIMIT 1"
            )
            assert step_status == "failed", f"Expected step status=failed, got: {step_status!r}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_entry_proceeds_when_ticker_not_held(self):
        """Entry not blocked when ticker is absent from the latest sync's positions."""
        ticker = "AHG2"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        # No live_position seeded for AHG2
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            reason = (data.get("reason") or data.get("risk_reason") or "").lower()
            assert "already held" not in reason, f"Got unexpected 'already held': {reason}"
            trace_id = data["trace_id"]
            step_status = psql_val(
                f"SELECT status FROM execution_steps "
                f"WHERE trace_id = '{trace_id}' AND step_name = 'already_held_check' AND status = 'failed' LIMIT 1"
            )
            assert step_status == "", f"Expected no failed already_held_check step, got: {step_status!r}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_entry_proceeds_when_no_sync_data_at_all(self):
        """Entry not blocked when no successful sync exists yet."""
        ticker = "AHG3"
        purge_successful_sync_runs()
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code in (200, 409)  # 409 = stale sync; guard must not fire
            data = r.json()
            reason = (data.get("reason") or data.get("risk_reason") or data.get("detail") or "").lower()
            assert "already held" not in reason, f"Got unexpected 'already held': {reason}"
        finally:
            cleanup_run(run_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_entry_with_qty_zero_in_live_positions_is_not_blocked(self):
        """Defensive: a 0-qty row in live_positions does not trigger the guard.

        The SQL has `lp.qty > 0` so a 0-qty row would return no match.
        We seed it explicitly to verify the guard still passes.
        """
        ticker = "AHG4"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        # Seed a 0-qty position (closed) — the SQL guard filters these out
        psql(
            f"INSERT INTO live_positions (sync_run_id, ticker, qty, current_price) "
            f"VALUES ('{sync_id}', '{ticker}', 0, 50.0)"
        )
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            reason = (data.get("reason") or data.get("risk_reason") or "").lower()
            assert "already held" not in reason, f"Got unexpected 'already held': {reason}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_buy_add_not_blocked_when_ticker_held(self):
        """buy_add is exempt from the already-held guard (it's explicitly for held tickers)."""
        ticker = "AHG5"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        seed_live_position(sync_id, ticker, qty=50.0, price=50.0)
        psql(
            f"INSERT INTO live_positions (sync_run_id, ticker, qty, current_price, market_value) "
            f"SELECT '{sync_id}', '{ticker}', 50, 50.0, 2500.0 "
            f"WHERE NOT EXISTS (SELECT 1 FROM live_positions WHERE sync_run_id='{sync_id}' AND ticker='{ticker}')"
        )
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        # buy_add: actual_weight=0.02 (underweight vs target 0.05)
        intent_id = seed_delta_intent(run_id, ticker, "buy_add", weight=0.05, actual_weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code in (200, 400)
            data = r.json() if r.status_code == 200 else r.json()
            reason = (data.get("reason") or data.get("risk_reason") or data.get("detail") or "").lower()
            assert "already held" not in reason, f"Guard fired on buy_add: {reason}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_exit_not_blocked_when_ticker_held(self):
        """exit is exempt from the already-held guard."""
        ticker = "AHG6"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        seed_live_position(sync_id, ticker, qty=50.0, price=50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "exit")
        try:
            r = submit(intent_id)
            assert r.status_code in (200, 400)
            data = r.json()
            reason = (data.get("reason") or data.get("risk_reason") or data.get("detail") or "").lower()
            assert "already held" not in reason, f"Guard fired on exit: {reason}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_orders_by_ticker(ticker)

    def test_sell_trim_not_blocked_when_ticker_held(self):
        """sell_trim is exempt from the already-held guard."""
        ticker = "AHG7"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        seed_live_position(sync_id, ticker, qty=50.0, price=50.0)
        run_id = seed_delta_run()
        # sell_trim: actual_weight=0.06 > target 0.03
        intent_id = seed_delta_intent(run_id, ticker, "sell_trim", weight=0.03, actual_weight=0.06)
        try:
            r = submit(intent_id)
            assert r.status_code in (200, 400)
            data = r.json()
            reason = (data.get("reason") or data.get("risk_reason") or data.get("detail") or "").lower()
            assert "already held" not in reason, f"Guard fired on sell_trim: {reason}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_orders_by_ticker(ticker)

    def test_partial_fill_blocks_new_entry(self):
        """Partial fill: ticker already held (partial qty > 0) → entry blocked."""
        ticker = "AHG8"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        # Only 50 of 200 shares filled — partial fill, but broker holds qty=50
        seed_live_position(sync_id, ticker, qty=50.0, price=50.0)
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "failed", data
            reason = (data.get("reason") or data.get("risk_reason") or "").lower()
            assert "already held" in reason, f"Expected 'already held' in reason: {reason}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_stale_sync_entry_not_blocked_by_already_held_check(self):
        """Stale sync: _is_already_held returns False (defers to size_entry's guard).

        The already-held guard silently defers when the sync is too old,
        so the sizing step surfaces the clearer 'sync too old' error.
        """
        ticker = "AHG9"
        purge_successful_sync_runs()
        stale_hours = _EXIT_SYNC_MAX_AGE_HOURS + 1
        sync_id = seed_sync_run(100_000.0, age_hours=stale_hours)
        seed_live_position(sync_id, ticker, qty=100.0, price=50.0)
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            data = r.json() if r.status_code == 200 else r.json()
            reason = (data.get("reason") or data.get("risk_reason") or data.get("detail") or "").lower()
            assert "already held" not in reason, (
                f"already_held guard fired on stale sync — should defer to size_entry: {reason}"
            )
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_already_held_audit_trail(self):
        """Verify full audit trail: execution_traces, alpaca_orders, execution_steps."""
        ticker = "AHG10"
        sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        seed_live_position(sync_id, ticker, qty=100.0, price=50.0)
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.05)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "failed"
            trace_id = data["trace_id"]
            # execution_traces row
            trace_status = psql_val(
                f"SELECT status || '|' || COALESCE(notes, '') "
                f"FROM execution_traces WHERE trace_id = '{trace_id}'"
            )
            assert "failed" in trace_status, f"Expected trace status=failed: {trace_status!r}"
            assert "already_held" in trace_status, f"Expected notes=already_held: {trace_status!r}"
            # alpaca_orders row
            db = get_order_row(intent_id)
            assert db["status"] == "failed", db
            assert db["risk_approved"] == "false", db
            # execution_steps row
            step_status = psql_val(
                f"SELECT status FROM execution_steps "
                f"WHERE trace_id = '{trace_id}' AND step_name = 'already_held_check' LIMIT 1"
            )
            assert step_status == "failed", f"Expected step=failed, got: {step_status!r}"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)

    def test_position_closed_since_older_sync_does_not_block(self):
        """Position was held in an old sync but closed in the latest sync — not blocked."""
        ticker = "AHG11"
        # Old sync: ticker was held
        old_sync_id = seed_sync_run(100_000.0, age_hours=10.0)
        seed_live_position(old_sync_id, ticker, qty=100.0, price=50.0)
        # New sync: ticker NOT in positions (position closed)
        new_sync_id = seed_sync_run(100_000.0, age_hours=0.0)
        # No live_position for new_sync_id and ticker
        seed_daily_price(ticker, 50.0)
        run_id = seed_delta_run()
        intent_id = seed_delta_intent(run_id, ticker, "entry", weight=0.02)
        try:
            r = submit(intent_id)
            assert r.status_code == 200
            data = r.json()
            reason = (data.get("reason") or data.get("risk_reason") or "").lower()
            assert "already held" not in reason, (
                f"Guard fired even though latest sync shows no position: {reason}"
            )
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(old_sync_id)
            cleanup_sync_run(new_sync_id)
            cleanup_daily_price(ticker)
            cleanup_orders_by_ticker(ticker)
