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


pytestmark = pytest.mark.skipif(
    not _stack_up(), reason="Docker stack not reachable on :8012"
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


def seed_sync_run(account_value: float = 100_000.0, age_hours: float = 0.0) -> str:
    run_id = new_id()
    completed_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    psql(
        f"INSERT INTO alpaca_sync_runs (run_id, status, account_value, completed_at) "
        f"VALUES ('{run_id}', 'success', {account_value}, '{completed_at}')"
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
            assert "credential" in (data.get("reason") or "").lower(), data
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
            assert "credential" in db["error_message"].lower(), db
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


# ── Test: scheduled mode (opg) ────────────────────────────────────────────────

class TestScheduledMode:
    TICKER = "TSCH1"

    def test_scheduled_mode_creates_opg_order(self):
        """mode='scheduled' produces time_in_force='opg' in alpaca_orders."""
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
            assert tif == "opg", f"Expected opg, got '{tif}'"
        finally:
            cleanup_run(run_id)
            cleanup_sync_run(sync_id)
            cleanup_daily_price(self.TICKER)

    def test_immediate_mode_creates_day_order(self):
        """mode='immediate' produces time_in_force='day' in alpaca_orders."""
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
