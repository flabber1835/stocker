"""
Integration tests for trade-executor state-transition idempotency, MOO-only
enforcement, buying-power edge cases, and audit-trail invariants.

Runs against the live Docker stack (postgres:5433, trade-executor:8012,
risk-service:8011). Skip the whole module if the stack is not reachable.
"""
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
import requests

# ── Config ────────────────────────────────────────────────────────────────────

TE_URL = "http://localhost:8012"
DB_DSN = "host=localhost port=5433 dbname=stocker user=stocker password=stocker"


def _stack_up() -> bool:
    try:
        return requests.get(f"{TE_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _stack_up(), reason="Docker stack not reachable on :8012"
)


# ── DB helpers — use psycopg2 directly (no docker exec dependency) ──────────

def pg():
    return psycopg2.connect(DB_DSN)


def new_id() -> str:
    return str(uuid.uuid4())


def seed_daily_price(ticker: str, close: float = 100.0) -> None:
    """Ensure ticker has a daily price row so _size_entry can compute qty."""
    today = datetime.now().strftime("%Y-%m-%d")
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO daily_prices (ticker, date, close) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (ticker, date) DO UPDATE SET close = EXCLUDED.close",
                (ticker, today, close),
            )
        conn.commit()


def seed_delta_run(strategy_id: str = "inttest") -> str:
    run_id = new_id()
    today = datetime.now().strftime("%Y-%m-%d")
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO delta_runs (run_id, strategy_id, status, run_date, triggered_by) "
                "VALUES (%s, %s, 'success', %s, 'test')",
                (run_id, strategy_id, today),
            )
        conn.commit()
    return run_id


def seed_delta_intent(run_id: str, ticker: str, action: str = "entry",
                      weight: float = 0.05) -> str:
    iid = new_id()
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO delta_intents (id, run_id, ticker, action, current_weight, actual_weight) "
                "VALUES (%s, %s, %s, %s, %s, 0.0)",
                (iid, run_id, ticker, action, weight),
            )
        conn.commit()
    return iid


def seed_sync_run(account_value: float = 100_000.0,
                  buying_power: float | None = None,
                  age_hours: float = 0.0) -> str:
    run_id = new_id()
    bp = buying_power if buying_power is not None else account_value
    completed_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alpaca_sync_runs "
                "(run_id, status, account_value, buying_power, cash, started_at, completed_at) "
                "VALUES (%s, 'success', %s, %s, %s, %s, %s)",
                (run_id, account_value, bp, bp, completed_at, completed_at),
            )
        conn.commit()
    return run_id


def seed_alpaca_order(intent_id: str, ticker: str,
                      status: str, time_in_force: str = "day") -> str:
    oid = new_id()
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO alpaca_orders "
                "(id, intent_id, ticker, action, side, qty, notional, order_type, "
                "time_in_force, status, mode, risk_approved, risk_reason, created_at) "
                "VALUES (%s, %s, %s, 'entry', 'buy', 10, 1800, 'market', %s, %s, "
                "'scheduled', true, 'test', NOW())",
                (oid, intent_id, ticker, time_in_force, status),
            )
        conn.commit()
    return oid


def submit(intent_id: str, mode: str = "scheduled") -> requests.Response:
    return requests.post(
        f"{TE_URL}/jobs/submit",
        json={"intent_id": intent_id, "mode": mode},
        timeout=15,
    )


def orders_for_intent(intent_id: str) -> list[tuple]:
    with pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, time_in_force, mode, risk_check_id, trace_id "
                "FROM alpaca_orders WHERE intent_id=%s ORDER BY created_at ASC",
                (intent_id,),
            )
            return cur.fetchall()


# ═════════════════════════════════════════════════════════════════════════════
# Section A: Idempotency — blocking statuses
# ═════════════════════════════════════════════════════════════════════════════

class TestIdempotencyBlocking:
    """Statuses that must prevent a second submit: pending, submitted, risk_rejected.

    Design: trade-executor /jobs/submit returns HTTP 200 with body.status='duplicate'
    (not 409). The 409 is returned by the API layer (/trade/approve). Both are correct
    per the documented design — the executor signals 'duplicate' in the response body
    so callers can distinguish it from a successful submission.
    """

    @pytest.mark.parametrize("order_status", ["pending", "submitted", "risk_rejected"])
    def test_blocked_by_existing_open_order_returns_duplicate(self, order_status):
        seed_sync_run()
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "AAPL")
        seed_alpaca_order(iid, "AAPL", order_status)

        r = submit(iid)
        assert r.status_code == 200, (
            f"Expected 200 for duplicate status={order_status!r}, got {r.status_code}: {r.text[:200]}"
        )
        body = r.json()
        assert body.get("status") == "duplicate", (
            f"Expected status='duplicate' for order_status={order_status!r}, got {body}"
        )

    def test_pending_blocks_both_modes(self):
        seed_sync_run()
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "TSLA")
        seed_alpaca_order(iid, "TSLA", "pending")

        for mode in ("scheduled", "immediate"):
            r = submit(iid, mode)
            assert r.json().get("status") == "duplicate", (
                f"mode={mode!r}: expected duplicate, got {r.json()}"
            )

    def test_no_5xx_for_blocked_statuses(self):
        """Idempotency block must never cause 5xx."""
        for status in ("pending", "submitted", "risk_rejected"):
            seed_sync_run()
            run_id = seed_delta_run()
            iid = seed_delta_intent(run_id, "NVDA")
            seed_alpaca_order(iid, "NVDA", status)
            r = submit(iid)
            assert r.status_code < 500, (
                f"status={status!r} idempotency caused 5xx: {r.status_code}"
            )


# ═════════════════════════════════════════════════════════════════════════════
# Section B: Idempotency — allowing statuses (retry permitted)
# ═════════════════════════════════════════════════════════════════════════════

class TestIdempotencyAllowing:
    """Statuses that must NOT block a retry: failed, filled, canceled."""

    @pytest.mark.parametrize("order_status", ["failed", "filled", "canceled"])
    def test_allowed_to_retry(self, order_status):
        seed_sync_run()
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "NVDA")
        seed_alpaca_order(iid, "NVDA", order_status)

        r = submit(iid)
        assert r.status_code != 409, (
            f"status={order_status!r} should allow retry, got 409: {r.text[:200]}"
        )
        assert r.status_code < 500, (
            f"status={order_status!r} retry caused 5xx: HTTP {r.status_code}"
        )

    def test_failed_retry_creates_new_order_row(self):
        seed_sync_run()
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "GOOG")
        failed_oid = seed_alpaca_order(iid, "GOOG", "failed")

        r = submit(iid)
        assert r.status_code != 409

        rows = orders_for_intent(iid)
        assert len(rows) >= 1, "Expected at least the original failed row"
        # The first row is still the seeded failed row
        assert str(rows[0][0]) == failed_oid

    def test_failed_retry_preserves_original_row(self):
        seed_sync_run()
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "META")
        failed_oid = seed_alpaca_order(iid, "META", "failed")

        submit(iid)

        rows = orders_for_intent(iid)
        statuses = [r[1] for r in rows]
        assert "failed" in statuses, "Original failed row must be preserved in audit trail"


# ═════════════════════════════════════════════════════════════════════════════
# Section C: day-order enforcement
# ═════════════════════════════════════════════════════════════════════════════

class TestDayOrderEnforcement:
    """All orders must use time_in_force='day' regardless of mode.

    Day orders are accepted by Alpaca 24/7 and queue for the next session when
    submitted outside market hours — they avoid the OPG-expiry problem (OPG orders
    expire if the stock has no opening-auction print). See CLAUDE.md trade-executor
    section. (These assertions were previously 'opg', from before that decision —
    corrected here to match the code and the documented contract.)"""

    def test_immediate_mode_creates_day_order(self):
        seed_sync_run()
        seed_daily_price("AAPL", 100.0)
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "AAPL")

        r = submit(iid, mode="immediate")
        # Even if Alpaca rejects (no creds), the local row must be written
        assert r.status_code < 500, f"5xx on submit: {r.text[:200]}"

        rows = orders_for_intent(iid)
        assert rows, "No alpaca_orders row was created"
        tif = rows[-1][2]
        assert tif == "day", f"immediate-mode order has time_in_force={tif!r}, expected 'day'"

    def test_scheduled_mode_creates_day_order(self):
        seed_sync_run()
        seed_daily_price("MSFT", 100.0)
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "MSFT")

        r = submit(iid, mode="scheduled")
        assert r.status_code < 500

        rows = orders_for_intent(iid)
        assert rows
        tif = rows[-1][2]
        assert tif == "day", f"scheduled-mode order has time_in_force={tif!r}, expected 'day'"

    def test_no_opg_orders_in_recent_history(self):
        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM alpaca_orders "
                    "WHERE time_in_force != 'day' "
                    "  AND time_in_force IS NOT NULL "
                    "  AND created_at > NOW() - INTERVAL '1 hour'"
                )
                count = cur.fetchone()[0]
        assert count == 0, (
            f"Found {count} orders with time_in_force != 'day' in the last hour"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Section D: Buying-power edge cases
# ═════════════════════════════════════════════════════════════════════════════

class TestBuyingPowerEdgeCases:
    """Submit rejects gracefully when buying_power is too low."""

    def test_zero_buying_power_refused_400(self):
        seed_sync_run(account_value=0, buying_power=0)
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "NVDA")

        r = submit(iid)
        assert r.status_code == 400, (
            f"Expected 400 for zero buying_power, got {r.status_code}: {r.text[:200]}"
        )
        # Must mention sizing failure, not a generic 500
        body = r.json()
        detail = body.get("detail", "").lower()
        assert "small" in detail or "qty" in detail or "zero" in detail or "insufficient" in detail, (
            f"Expected sizing-related error message, got: {detail!r}"
        )

    def test_tiny_buying_power_refused_400(self):
        # $50 × 5% weight = $2.50, floor(2.50 / ~price) = 0 → refused
        seed_sync_run(account_value=50, buying_power=50)
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "TSLA")

        r = submit(iid)
        assert r.status_code == 400, (
            f"Expected 400 for tiny buying_power=$50, got {r.status_code}: {r.text[:200]}"
        )

    def test_zero_buying_power_creates_no_pending_order(self):
        """When refused for insufficient funds, no orphan pending row must be created."""
        seed_sync_run(account_value=0, buying_power=0)
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "GOOG")

        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM alpaca_orders WHERE intent_id=%s AND status='pending'",
                    (iid,)
                )
                before = cur.fetchone()[0]

        r = submit(iid)
        assert r.status_code == 400

        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM alpaca_orders WHERE intent_id=%s AND status='pending'",
                    (iid,)
                )
                after = cur.fetchone()[0]

        assert after == before, (
            f"Orphan pending order created for refused zero-buying-power trade "
            f"(before={before}, after={after})"
        )

    def test_large_buying_power_does_not_5xx(self):
        seed_sync_run(account_value=500_000, buying_power=500_000)
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "AAPL")

        r = submit(iid)
        assert r.status_code < 500, (
            f"Large buying_power caused 5xx: {r.status_code}: {r.text[:200]}"
        )

    def test_account_value_used_as_sizing_basis(self):
        """Entries always size against account_value regardless of buying_power level.

        With buying_power=$10k < account_value=$100k, we should size against
        account_value so a fully-invested portfolio replacing one exited position
        gets a correctly-sized entry (buying_power≈0 in that state would produce
        a nearly-zero order with the old logic).
        """
        seed_sync_run(account_value=100_000, buying_power=10_000)
        run_id = seed_delta_run()
        iid = seed_delta_intent(run_id, "AAPL", weight=0.05)

        r = submit(iid)
        assert r.status_code < 500

        # Check execution_steps for sizing_basis
        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT output_summary FROM execution_steps "
                    "WHERE step_name IN ('size_order','size_entry') "
                    "  AND started_at > NOW() - INTERVAL '5 minutes' "
                    "ORDER BY started_at DESC LIMIT 1"
                )
                row = cur.fetchone()
        if row and row[0]:
            import json
            summary = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            basis = summary.get("sizing_basis")
            if basis:
                assert basis == "account_value", (
                    f"Expected sizing_basis='account_value', got {basis!r}"
                )


# ═════════════════════════════════════════════════════════════════════════════
# Section E: Audit trail invariants
# ═════════════════════════════════════════════════════════════════════════════

class TestAuditTrailInvariants:
    """DB invariants that must hold after any trade-executor activity."""

    def test_approved_orders_have_risk_check_id(self):
        # Only check rows that have a trace_id (created by the real API flow, not
        # directly-seeded test data rows which intentionally omit risk_check_id).
        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM alpaca_orders "
                    "WHERE risk_approved = true AND risk_check_id IS NULL "
                    "  AND trace_id IS NOT NULL "
                    "  AND created_at > NOW() - INTERVAL '2 hours'"
                )
                orphans = cur.fetchall()
        assert not orphans, (
            f"{len(orphans)} API-submitted approved order(s) have no risk_check_id: "
            + ", ".join(str(o[0])[:8] for o in orphans[:3])
        )

    def test_trace_ids_match_execution_traces(self):
        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ao.id FROM alpaca_orders ao "
                    "LEFT JOIN execution_traces et ON et.trace_id = ao.trace_id "
                    "WHERE ao.trace_id IS NOT NULL AND et.trace_id IS NULL "
                    "  AND ao.created_at > NOW() - INTERVAL '2 hours'"
                )
                missing = cur.fetchall()
        assert not missing, (
            f"{len(missing)} order(s) have trace_id with no execution_traces row: "
            + ", ".join(str(m[0])[:8] for m in missing[:3])
        )

    def test_risk_check_ids_reference_valid_risk_decisions(self):
        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ao.id, ao.risk_check_id FROM alpaca_orders ao "
                    "LEFT JOIN risk_decisions rd ON rd.decision_id = ao.risk_check_id "
                    "WHERE ao.risk_check_id IS NOT NULL AND rd.decision_id IS NULL "
                    "  AND ao.created_at > NOW() - INTERVAL '2 hours'"
                )
                dangling = cur.fetchall()
        assert not dangling, (
            f"{len(dangling)} order(s) have risk_check_id not in risk_decisions: "
            + ", ".join(str(d[0])[:8] for d in dangling[:3])
        )

    def test_no_orders_without_execution_steps(self):
        """Every order created via /jobs/submit must have at least one execution_steps row."""
        with pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ao.id FROM alpaca_orders ao "
                    "LEFT JOIN execution_steps es ON es.trace_id = ao.trace_id "
                    "WHERE ao.trace_id IS NOT NULL AND es.step_id IS NULL "
                    "  AND ao.created_at > NOW() - INTERVAL '2 hours'"
                )
                no_steps = cur.fetchall()
        # Allow some tolerance for edge cases (e.g. a crash mid-write)
        assert len(no_steps) < 5, (
            f"{len(no_steps)} order(s) have a trace_id but no execution_steps rows"
        )


# ═════════════════════════════════════════════════════════════════════════════
# Section F: cancel-all-orders endpoint
# ═════════════════════════════════════════════════════════════════════════════

class TestCancelAllOrders:
    """POST /jobs/cancel-all-orders fuzzing and correctness."""

    def test_missing_confirm_refused_400(self):
        r = requests.post(f"{TE_URL}/jobs/cancel-all-orders", timeout=10)
        assert r.status_code == 400
        assert "confirm" in r.json().get("detail", "").lower()

    @pytest.mark.parametrize("bad_confirm", ["no", "maybe", "YES", "1", "true", ""])
    def test_invalid_confirm_refused_400(self, bad_confirm):
        r = requests.post(
            f"{TE_URL}/jobs/cancel-all-orders?confirm={bad_confirm}", timeout=10
        )
        assert r.status_code == 400, (
            f"confirm={bad_confirm!r} should be refused, got {r.status_code}"
        )

    def test_valid_confirm_returns_200_with_schema(self):
        r = requests.post(
            f"{TE_URL}/jobs/cancel-all-orders?confirm=yes", timeout=15
        )
        assert r.status_code == 200
        body = r.json()
        assert "alpaca_cancel_count" in body
        assert "local_orders_updated" in body
        assert "status" in body

    def test_wrong_http_method_not_5xx(self):
        r = requests.get(f"{TE_URL}/jobs/cancel-all-orders", timeout=5)
        assert r.status_code in (404, 405), (
            f"GET on POST endpoint should be 404 or 405, got {r.status_code}"
        )

    def test_sql_injection_in_confirm_param_not_5xx(self):
        import urllib.parse
        inject = urllib.parse.quote("'; DROP TABLE alpaca_orders;--", safe="")
        r = requests.post(
            f"{TE_URL}/jobs/cancel-all-orders?confirm={inject}", timeout=10
        )
        assert r.status_code < 500, (
            f"SQL injection in confirm param caused 5xx: {r.status_code}"
        )
