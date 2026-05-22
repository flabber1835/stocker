"""
Dynamic cold-boot delta test.

Tests three core scenarios against the live database:
  1. Empty Alpaca  — no live positions, all target tickers should become ENTRY
  2. Partial Alpaca — mix of overlapping + orphan junk positions
  3. Full Alpaca   — all target tickers already held, all should be HOLD

Also tests edge cases:
  - Weight math: entry weights match portfolio_holdings exactly
  - triggered_by='scheduler' on /jobs/delta runs
  - Orphan junk tickers always EXIT regardless of rank
  - /runs/delta-latest only returns scheduler runs
  - Idempotency: two rapid /jobs/delta calls don't race

Usage:
  python dynamic_test_cold_boot.py
"""
import sys
import time
import json
import random
import string
import uuid
import asyncio
import asyncpg
import httpx
from datetime import date, datetime
from typing import Optional

# ── Connection config ─────────────────────────────────────────────────────────
PIPELINE_URL = "http://localhost:8018"
DB_URL = "postgresql://stocker:stocker@localhost:5433/stocker"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"

_failures = 0
_passes = 0


def ok(msg: str):
    global _passes
    _passes += 1
    print(f"  {PASS} {msg}")


def fail(msg: str):
    global _failures
    _failures += 1
    print(f"  {FAIL} {msg}")


def section(title: str):
    print(f"\n{'═'*60}")
    print(f"  {title}")
    print(f"{'═'*60}")


def info(msg: str):
    print(f"  {INFO} {msg}")


def assert_eq(label: str, got, expected):
    if got == expected:
        ok(f"{label}: {got!r}")
    else:
        fail(f"{label}: got {got!r}, expected {expected!r}")


def assert_approx(label: str, got: float, expected: float, tol: float = 1e-6):
    if abs(got - expected) <= tol:
        ok(f"{label}: {got:.8f} ≈ {expected:.8f}")
    else:
        fail(f"{label}: got {got:.8f}, expected {expected:.8f} (diff={abs(got-expected):.2e})")


def assert_true(label: str, value: bool, detail: str = ""):
    if value:
        ok(f"{label}" + (f" [{detail}]" if detail else ""))
    else:
        fail(f"{label}" + (f" [{detail}]" if detail else ""))


# ── DB helpers ────────────────────────────────────────────────────────────────

async def db():
    return await asyncpg.connect(DB_URL)


async def get_latest_portfolio(conn) -> dict[str, float]:
    """Returns {ticker: weight} from the latest successful portfolio run."""
    rows = await conn.fetch("""
        SELECT ph.ticker, ph.weight
        FROM portfolio_holdings ph
        JOIN portfolio_runs pr ON ph.run_id = pr.run_id
        WHERE pr.run_id = (
            SELECT run_id FROM portfolio_runs
            WHERE status='success' ORDER BY portfolio_date DESC LIMIT 1
        )
    """)
    return {r["ticker"]: float(r["weight"]) for r in rows}


async def get_live_tickers(conn) -> set[str]:
    rows = await conn.fetch("SELECT ticker FROM live_positions")
    return {r["ticker"] for r in rows}


async def set_live_positions(conn, positions: dict[str, float]):
    """Replace live_positions with the given {ticker: qty} dict.

    Always creates a fresh alpaca_sync_run with status='success' and
    completed_at=NOW() so the delta engine's query
      (WHERE status='success' ORDER BY completed_at DESC)
    picks up exactly this sync run — not a stale one.
    """
    run_id = str(uuid.uuid4())
    await conn.execute("""
        INSERT INTO alpaca_sync_runs (run_id, status, started_at, completed_at, account_value)
        VALUES ($1, 'success', NOW(), NOW(), 100000)
    """, run_id)

    await conn.execute("DELETE FROM live_positions")
    for ticker, qty in positions.items():
        await conn.execute("""
            INSERT INTO live_positions
              (ticker, qty, market_value, side, sync_run_id, synced_at)
            VALUES ($1, $2, $3, 'long', $4, NOW())
        """, ticker, float(qty), float(qty) * 100, run_id)


async def get_latest_delta_run(conn) -> Optional[dict]:
    row = await conn.fetchrow("""
        SELECT run_id, status, entries_count, exits_count, holds_count, watches_count,
               triggered_by, run_date
        FROM delta_runs
        ORDER BY started_at DESC LIMIT 1
    """)
    return dict(row) if row else None


async def get_latest_scheduler_delta_run(conn) -> Optional[dict]:
    """What /runs/delta-latest returns: only triggered_by='scheduler' runs."""
    row = await conn.fetchrow("""
        SELECT run_id, status, entries_count, exits_count, holds_count, watches_count,
               triggered_by, run_date
        FROM delta_runs
        WHERE triggered_by = 'scheduler'
        ORDER BY started_at DESC LIMIT 1
    """)
    return dict(row) if row else None


async def get_delta_intents_for_run(conn, run_id: str) -> list[dict]:
    rows = await conn.fetch("""
        SELECT ticker, action, current_weight
        FROM delta_intents
        WHERE run_id = $1
        ORDER BY ticker
    """, run_id)
    return [dict(r) for r in rows]


async def trigger_delta_and_wait(max_wait: int = 60) -> dict:
    """POST /jobs/delta and poll until completed. Returns the response JSON."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{PIPELINE_URL}/jobs/delta", timeout=10)
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"/jobs/delta returned {resp.status_code}: {resp.text}")
        data = resp.json()
        if data.get("status") == "already_running":
            # Wait for it to finish
            pass

    # Poll /runs/delta-latest
    start = time.time()
    while time.time() - start < max_wait:
        await asyncio.sleep(1)
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{PIPELINE_URL}/runs/delta-latest", timeout=10)
            if resp.status_code == 200:
                d = resp.json()
                if d.get("status") in ("success", "failed", "error"):
                    return d
            elif resp.status_code == 404:
                pass  # not yet
    raise TimeoutError("delta run did not complete within timeout")


async def get_delta_latest_via_http() -> Optional[dict]:
    """GET /runs/delta-latest endpoint directly."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{PIPELINE_URL}/runs/delta-latest", timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1: Empty Alpaca (no live positions)
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_empty_alpaca(conn, target: dict[str, float]):
    section("SCENARIO 1: Empty Alpaca (cold boot — no live positions)")
    info(f"Target portfolio: {len(target)} stocks")
    info("Setting live_positions to EMPTY")

    await set_live_positions(conn, {})
    live = await get_live_tickers(conn)
    assert_eq("live_positions count after clear", len(live), 0)

    info("Triggering /jobs/delta...")
    result = await trigger_delta_and_wait()

    assert_eq("delta run status", result.get("status"), "success")
    assert_eq("triggered_by", result.get("triggered_by"), "scheduler")

    entries = result.get("entries_count", 0)
    exits   = result.get("exits_count", 0)
    holds   = result.get("holds_count", 0)

    info(f"Results: entries={entries}, exits={exits}, holds={holds}")

    # All target tickers should be ENTRY, no HOLD, no EXIT
    assert_eq("entries = target portfolio size", entries, len(target))
    assert_eq("exits = 0 (no live positions to exit)", exits, 0)
    assert_eq("holds = 0 (nothing was held)", holds, 0)

    # Verify weight math on intents
    run_row = await get_latest_scheduler_delta_run(conn)
    intents = await get_delta_intents_for_run(conn, run_row["run_id"])

    entry_intents = {i["ticker"]: i for i in intents if i["action"] == "entry"}
    info(f"Entry intents: {len(entry_intents)}")

    # Sample check: first 5 tickers — weights must match portfolio_holdings exactly
    checked = 0
    for ticker, expected_weight in sorted(target.items())[:5]:
        if ticker in entry_intents:
            got_weight = float(entry_intents[ticker]["current_weight"] or 0)
            assert_approx(
                f"  {ticker} weight (entry)",
                got_weight,
                expected_weight,
                tol=1e-6
            )
            checked += 1

    assert_true("Weight math spot-checked on 5 tickers", checked == 5)

    # Verify all target tickers have entry intents
    missing = set(target.keys()) - set(entry_intents.keys())
    assert_true(
        f"All target tickers have entry intents",
        len(missing) == 0,
        f"missing: {missing}" if missing else ""
    )

    # /runs/delta-latest endpoint returns only scheduler runs
    http_result = await get_delta_latest_via_http()
    assert_true("/runs/delta-latest returns a result", http_result is not None)
    if http_result:
        assert_eq("/runs/delta-latest triggered_by", http_result.get("triggered_by"), "scheduler")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 2: Partial Alpaca — overlap + junk orphans
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_partial_alpaca(conn, target: dict[str, float]):
    section("SCENARIO 2: Partial Alpaca — overlap + junk orphans")

    # Pick 4 real stocks from target + 2 junk tickers not in target
    target_sample = list(target.keys())[:4]
    junk = ["FAKE9", "FAKEZ"]

    live_set = {t: 100.0 for t in target_sample + junk}
    info(f"Setting live positions: {target_sample} (in target) + {junk} (orphan junk)")
    await set_live_positions(conn, live_set)

    live = await get_live_tickers(conn)
    assert_eq("live_positions count", len(live), len(target_sample) + len(junk))

    info("Triggering /jobs/delta...")
    result = await trigger_delta_and_wait()
    assert_eq("delta run status", result.get("status"), "success")
    assert_eq("triggered_by", result.get("triggered_by"), "scheduler")

    entries = result.get("entries_count", 0)
    exits   = result.get("exits_count", 0)
    holds   = result.get("holds_count", 0)
    info(f"Results: entries={entries}, exits={exits}, holds={holds}")

    expected_entries = len(target) - len(target_sample)  # target - what's already held
    expected_exits   = len(junk)                          # junk orphans → exit
    expected_holds   = len(target_sample)                 # overlap → hold

    assert_eq(f"entries = {expected_entries} (target minus held)", entries, expected_entries)
    assert_eq(f"exits = {len(junk)} (orphan junk → exit)", exits, expected_exits)
    assert_eq(f"holds = {len(target_sample)} (overlap)", holds, expected_holds)

    # Verify total intents account for all tickers
    total = entries + exits + holds
    assert_true(
        f"entries+exits+holds = {total} covers all tickers",
        total == len(target) + len(junk),
        f"expected {len(target) + len(junk)}"
    )

    # Verify weight math
    run_row = await get_latest_scheduler_delta_run(conn)
    intents = await get_delta_intents_for_run(conn, run_row["run_id"])
    intent_map = {i["ticker"]: i for i in intents}

    # Holds: weight must equal target weight
    for ticker in target_sample:
        if ticker in intent_map:
            d = intent_map[ticker]
            assert_eq(f"  {ticker} intent_type", d["action"], "hold")
            got = float(d["current_weight"] or 0)
            assert_approx(f"  {ticker} hold weight", got, target[ticker])

    # Junk orphans: must be EXIT
    for ticker in junk:
        if ticker in intent_map:
            d = intent_map[ticker]
            assert_eq(f"  {ticker} intent_type (junk orphan)", d["action"], "exit")
        else:
            info(f"  {ticker} not in intents (may be missing from universe — OK for junk)")

    # Entry intents: tickers in target but not held
    not_held = set(target.keys()) - set(target_sample)
    entry_intents = {i["ticker"]: i for i in intents if i["action"] == "entry"}

    for ticker in list(not_held)[:3]:
        if ticker in entry_intents:
            got = float(entry_intents[ticker]["current_weight"] or 0)
            assert_approx(f"  {ticker} entry weight", got, target[ticker])

    # Verify no target ticker is misclassified as exit
    target_exits = [i["ticker"] for i in intents if i["action"] == "exit" and i["ticker"] in target]
    assert_true(
        "No target ticker misclassified as EXIT",
        len(target_exits) == 0,
        f"wrongly exited: {target_exits}" if target_exits else ""
    )


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3: Full Alpaca — everything held
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_full_alpaca(conn, target: dict[str, float]):
    section("SCENARIO 3: Full Alpaca — entire target portfolio already held")

    # Put every target ticker in live_positions
    live_set = {t: 100.0 for t in target.keys()}
    info(f"Setting live positions: ALL {len(target)} target tickers")
    await set_live_positions(conn, live_set)

    live = await get_live_tickers(conn)
    assert_eq("live_positions count = target size", len(live), len(target))

    info("Triggering /jobs/delta...")
    result = await trigger_delta_and_wait()
    assert_eq("delta run status", result.get("status"), "success")

    entries = result.get("entries_count", 0)
    exits   = result.get("exits_count", 0)
    holds   = result.get("holds_count", 0)
    info(f"Results: entries={entries}, exits={exits}, holds={holds}")

    assert_eq("entries = 0 (all already held)", entries, 0)
    assert_eq("exits = 0 (no orphans)", exits, 0)
    assert_eq("holds = target size", holds, len(target))

    # Weight math: every hold has correct target weight
    run_row = await get_latest_scheduler_delta_run(conn)
    intents = await get_delta_intents_for_run(conn, run_row["run_id"])
    intent_map = {i["ticker"]: i for i in intents}

    weight_errors = []
    for ticker, expected_weight in target.items():
        if ticker in intent_map:
            got = float(intent_map[ticker]["current_weight"] or 0)
            if abs(got - expected_weight) > 1e-6:
                weight_errors.append(f"{ticker}: got={got:.8f}, exp={expected_weight:.8f}")

    assert_true(
        f"All {holds} holds have correct target weights",
        len(weight_errors) == 0,
        "; ".join(weight_errors[:3]) if weight_errors else ""
    )


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4: Corner cases
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_corner_cases(conn, target: dict[str, float]):
    section("SCENARIO 4: Corner cases")

    # ── 4a: triggered_by isolation
    info("4a: /runs/delta-latest only returns scheduler-triggered runs")
    # We'll verify that all runs from our tests have triggered_by='scheduler'
    rows = await conn.fetch("""
        SELECT triggered_by, COUNT(*) as cnt
        FROM delta_runs
        WHERE triggered_by = 'scheduler'
        GROUP BY triggered_by
    """)
    scheduler_count = rows[0]["cnt"] if rows else 0
    assert_true(
        f"At least 3 scheduler delta runs exist (one per scenario)",
        scheduler_count >= 3,
        f"found {scheduler_count}"
    )

    # ── 4b: pipeline delta runs are NOT returned by /runs/delta-latest
    pipeline_rows = await conn.fetch("""
        SELECT COUNT(*) as cnt FROM delta_runs WHERE triggered_by = 'pipeline'
    """)
    pipeline_count = pipeline_rows[0]["cnt"] if pipeline_rows else 0
    info(f"4b: pipeline-triggered delta runs in DB: {pipeline_count}")

    http_result = await get_delta_latest_via_http()
    if http_result:
        assert_eq("4b: /runs/delta-latest only returns scheduler run", http_result.get("triggered_by"), "scheduler")

    # ── 4c: empty target portfolio (portfolio-builder hasn't run yet — cold start)
    info("4c: Simulating cold start — no portfolio_holdings at all (fallback mode)")
    # We don't actually delete portfolio_holdings (destructive), so we just verify
    # the fallback branch isn't triggered when portfolio exists
    latest_port = await conn.fetchrow(
        "SELECT COUNT(*) as cnt FROM portfolio_holdings"
    )
    assert_true("4c: portfolio_holdings is populated", latest_port["cnt"] > 0)

    # ── 4d: weight precision — weight stored as NUMERIC(12,8)
    info("4d: Weight precision verification")
    await set_live_positions(conn, {})  # reset to empty
    result = await trigger_delta_and_wait()
    run_row = await get_latest_scheduler_delta_run(conn)
    intents = await get_delta_intents_for_run(conn, run_row["run_id"])

    # Check that sum of weights of all entry intents ≈ 1.0 (full portfolio)
    entry_intents = [i for i in intents if i["action"] == "entry"]
    total_weight = sum(float(i["current_weight"] or 0) for i in entry_intents)
    target_sum = sum(target.values())
    info(f"    Sum of entry weights: {total_weight:.8f}")
    info(f"    Sum of target weights: {target_sum:.8f}")
    assert_approx(
        "4d: sum of entry weights ≈ sum of target weights",
        total_weight,
        target_sum,
        tol=1e-4
    )

    # ── 4e: all-junk live positions (no overlap with target)
    info("4e: All-junk live positions — everything should EXIT")
    junk_positions = {"FAKE1": 100.0, "FAKE2": 200.0, "FAKE3": 50.0}
    await set_live_positions(conn, junk_positions)
    result = await trigger_delta_and_wait()

    exits = result.get("exits_count", 0)
    entries = result.get("entries_count", 0)
    holds = result.get("holds_count", 0)
    info(f"    entries={entries}, exits={exits}, holds={holds}")
    assert_eq("4e: exits = number of junk positions", exits, len(junk_positions))
    assert_eq("4e: holds = 0 (no overlap)", holds, 0)
    assert_eq("4e: entries = target portfolio size", entries, len(target))

    # ── 4f: single ticker that's BOTH in target and live (regression)
    info("4f: Single-ticker overlap regression check")
    single = list(target.keys())[0]
    single_weight = target[single]
    await set_live_positions(conn, {single: 10.0})
    result = await trigger_delta_and_wait()

    run_row = await get_latest_scheduler_delta_run(conn)
    intents = await get_delta_intents_for_run(conn, run_row["run_id"])
    single_intent = next((i for i in intents if i["ticker"] == single), None)

    assert_true(f"4f: {single} has an intent", single_intent is not None)
    if single_intent:
        assert_eq(f"4f: {single} is HOLD (in both)", single_intent["action"], "hold")
        got = float(single_intent["current_weight"] or 0)
        assert_approx(f"4f: {single} hold weight = target weight", got, single_weight)

    entries = result.get("entries_count", 0)
    holds   = result.get("holds_count", 0)
    assert_eq("4f: entries = target_size - 1", entries, len(target) - 1)
    assert_eq("4f: holds = 1", holds, 1)

    # ── 4g: idempotency — double trigger
    info("4g: Idempotency — two rapid /jobs/delta calls")
    await set_live_positions(conn, {})
    async with httpx.AsyncClient() as client:
        r1, r2 = await asyncio.gather(
            client.post(f"{PIPELINE_URL}/jobs/delta", timeout=10),
            client.post(f"{PIPELINE_URL}/jobs/delta", timeout=10),
        )
    statuses = {r1.json().get("status"), r2.json().get("status")}
    # One should be "started"/"running", the other "already_running"
    assert_true(
        "4g: Double trigger: one accepted, one rejected",
        "already_running" in statuses,
        f"statuses: {statuses}"
    )
    # Wait for completion
    await trigger_delta_and_wait(max_wait=60)


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5: Math deep-dive
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_math_deep_dive(conn, target: dict[str, float]):
    section("SCENARIO 5: Math deep-dive — precise weight verification")

    # Reset to empty Alpaca
    await set_live_positions(conn, {})
    result = await trigger_delta_and_wait()

    run_row = await get_latest_scheduler_delta_run(conn)
    intents = await get_delta_intents_for_run(conn, run_row["run_id"])
    intent_map = {i["ticker"]: i for i in intents}

    info(f"Checking weight fidelity for ALL {len(target)} target tickers...")
    weight_errors = []
    missing = []
    for ticker, expected in target.items():
        if ticker not in intent_map:
            missing.append(ticker)
            continue
        got = float(intent_map[ticker]["current_weight"] or 0)
        if abs(got - expected) > 1e-6:
            weight_errors.append(f"{ticker}: got={got:.8f} exp={expected:.8f} diff={abs(got-expected):.2e}")

    if missing:
        fail(f"Missing intents for: {missing}")
    else:
        ok(f"All {len(target)} target tickers have entry intents")

    if weight_errors:
        for e in weight_errors:
            fail(f"Weight mismatch: {e}")
    else:
        ok(f"All weights match portfolio_holdings to 6 decimal places")

    # Verify weight sum
    total = sum(float(i["current_weight"] or 0) for i in intents if i["action"] == "entry")
    target_total = sum(target.values())
    info(f"Total entry weight: {total:.8f}")
    info(f"Total target weight: {target_total:.8f}")
    assert_approx("Entry weight sum = target weight sum", total, target_total, tol=1e-4)

    # Verify entry count matches exactly
    assert_eq("Entry count = target size", result.get("entries_count"), len(target))
    assert_eq("Exit count = 0", result.get("exits_count"), 0)
    assert_eq("Hold count = 0", result.get("holds_count"), 0)

    # Cross-check via DB: intents in DB match HTTP response counts
    db_entries = sum(1 for i in intents if i["action"] == "entry")
    db_exits   = sum(1 for i in intents if i["action"] == "exit")
    db_holds   = sum(1 for i in intents if i["action"] == "hold")

    assert_eq("DB entry count matches API", db_entries, result.get("entries_count"))
    assert_eq("DB exit count matches API", db_exits, result.get("exits_count"))
    assert_eq("DB hold count matches API", db_holds, result.get("holds_count"))


# ─────────────────────────────────────────────────────────────────────────────
# RESTORE: put DB back to original state
# ─────────────────────────────────────────────────────────────────────────────

async def restore_original_state(conn, original_live: dict[str, float]):
    section("RESTORE: Returning DB to original live_positions state")
    await set_live_positions(conn, original_live)
    live = await get_live_tickers(conn)
    info(f"Restored live_positions: {sorted(live)}")
    ok(f"Restored {len(live)} positions")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print("\n" + "█"*60)
    print("  STOCKER COLD BOOT DYNAMIC TEST")
    print("█"*60)

    conn = await db()
    try:
        # Save original state
        target = await get_latest_portfolio(conn)
        original_live_rows = await conn.fetch(
            "SELECT ticker, qty FROM live_positions"
        )
        original_live = {r["ticker"]: float(r["qty"]) for r in original_live_rows}

        info(f"Target portfolio: {len(target)} stocks")
        info(f"Original live positions: {len(original_live)} stocks — {sorted(original_live.keys())}")

        if len(target) == 0:
            print("\n⚠ No portfolio holdings found — run portfolio-builder first.")
            return 1

        # Run all scenarios
        await scenario_empty_alpaca(conn, target)
        await scenario_partial_alpaca(conn, target)
        await scenario_full_alpaca(conn, target)
        await scenario_corner_cases(conn, target)
        await scenario_math_deep_dive(conn, target)

        # Restore
        await restore_original_state(conn, original_live)

    finally:
        await conn.close()

    # Results
    print(f"\n{'═'*60}")
    print(f"  RESULTS: {_passes} passed, {_failures} failed")
    print(f"{'═'*60}\n")

    return 0 if _failures == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
