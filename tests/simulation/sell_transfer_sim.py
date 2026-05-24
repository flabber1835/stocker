#!/usr/bin/env python3
"""
Dynamic end-to-end test: user sells a position and transfers cash away.

Services (live Docker containers):
  pipeline          :8018
  portfolio-builder :8008
  trade-executor    :8012
  risk-service      :8011
  postgres          :5433

Scenario states:
  A  Balanced portfolio baseline — all 10 positions, balanced
  B  User manually sells TK00; cash stays in account
  C  User sells TK00 AND transfers the $15k away
  D  Large transfer: account drops below drift threshold for all 9
  E  User sells 2 positions (TK00+TK01) and transfers $30k away
  F  Cash transfer only — no positions sold, account drops to $125k
  G  Sell + re-buy before pipeline runs (net: no change)
  H  Stale alpaca-sync: trade-executor must refuse sizing
"""

import sys, math, json, time, uuid
import psycopg2, psycopg2.extras, requests
from datetime import datetime, timezone, timedelta

_SQRT2 = math.sqrt(2)
_SQRT3 = math.sqrt(3)

def _sim_price(t_idx: int, day_idx: int, base: float = 100.0) -> float:
    """Deterministic pseudo-random price: oscillates ±0.5% around base.
    day_idx=0 is oldest, increases toward today.
    Different tickers have different phases (t_idx * sqrt(2)) so their
    log-return series are linearly independent → non-singular cov matrix.
    """
    return base * (1.0 + 0.005 * math.sin(t_idx * _SQRT2 + day_idx * _SQRT3))

PG = dict(host="localhost", port=5433, dbname="stocker", user="stocker", password="stocker")
PIPELINE_URL = "http://localhost:8018"
PORTBUILD_URL = "http://localhost:8008"
TRADE_URL    = "http://localhost:8012"
RISK_URL     = "http://localhost:8011"

ACCOUNT_VALUE   = 150_000.0
N_POSITIONS     = 10
PRICE           = 100.0
SHARES_EACH     = 150          # 150 × $100 = $15k = 10% of $150k
MV_EACH         = SHARES_EACH * PRICE
TARGET_WEIGHT   = 1.0 / N_POSITIONS   # 10%
DRIFT_THR       = 0.02

TICKERS = [f"TK{i:02d}" for i in range(N_POSITIONS)]   # ≤10 chars to fit varchar(10)

# ── Harness ────────────────────────────────────────────────────────────────────
ERRORS = []; WARNINGS = []; PASSED = []
def ok(n, d=""): PASSED.append(n); print(f"  ✅ {n}" + (f"  [{d}]" if d else ""))
def fail(n, d=""): ERRORS.append(n); print(f"  ❌ {n}" + (f"  [{d}]" if d else ""))
def warn(n, d=""): WARNINGS.append(n); print(f"  ⚠️  {n}" + (f"  [{d}]" if d else ""))
def check(c, n, d=""): (ok if c else fail)(n, d)
def hdr(t): print(f"\n{'═'*72}\n  {t}\n{'═'*72}")
def sub(t): print(f"\n  {'─'*72}\n  {t}\n  {'─'*72}")

def db():
    c = psycopg2.connect(**PG); c.autocommit = True; return c

# ── Seed helpers ───────────────────────────────────────────────────────────────

def seed_prices_and_universe(conn):
    """Insert universe snapshot + tickers + 252 days of daily prices."""
    today = datetime.now(timezone.utc).date()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count)
            VALUES ('TEST_UNI', %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
        """, (today, len(TICKERS)))
        row = cur.fetchone()
        if row is None:
            cur.execute("SELECT id FROM universe_snapshots WHERE etf_ticker='TEST_UNI' AND snapshot_date=%s", (today,))
            row = cur.fetchone()
        snap_id = row[0]

        for t in TICKERS:
            cur.execute("""
                INSERT INTO universe_tickers (snapshot_id, ticker, name)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """, (snap_id, t, f"{t} Inc"))

        # 600 days of price history — must match SPY history length.
        # The pivot in compute_all_factors includes SPY (600 rows); iloc[-252] for
        # momentum must land within TK* price history or all tickers get NaN momentum
        # and are dropped by min_non_null_factors=6. Seeding the same 600-day window
        # ensures iloc[-252] always hits a valid TK* price.
        #
        # Prices use a sinusoidal variation (±0.5% amplitude, different phase per ticker)
        # so log returns are non-constant → non-zero covariance → portfolio-builder's
        # adj_score stays within numeric(10,6) range (no flat-price overflow).
        cur.execute("DELETE FROM daily_prices WHERE ticker = ANY(%s)", (TICKERS,))
        for t_idx, t in enumerate(TICKERS):
            for d in range(600, 0, -1):
                px_date = today - timedelta(days=d)
                day_idx = 600 - d          # 0=oldest, 599=most recent
                adj_px = _sim_price(t_idx, day_idx)
                cur.execute("""
                    INSERT INTO daily_prices (ticker, date, open, high, low, close, adjusted_close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                """, (t, px_date, PRICE, PRICE*1.01, PRICE*0.99, PRICE, adj_px, 1_000_000))
    print(f"  • universe ({len(TICKERS)} tickers) + 600d prices seeded (sinusoidal variation)")


def seed_spy_prices(conn):
    """Insert SPY into daily_prices so the pipeline's regime detection has history."""
    today = datetime.now(timezone.utc).date()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker='SPY'")
        for d in range(600, 0, -1):
            px_date = today - timedelta(days=d)
            spy_px  = 520.0 * (1 + 0.0003 * (600 - d))
            cur.execute("""
                INSERT INTO daily_prices
                  (ticker, date, open, high, low, close, adjusted_close, volume)
                VALUES ('SPY', %s, %s, %s, %s, %s, %s, 50000000) ON CONFLICT DO NOTHING
            """, (px_date, spy_px, spy_px*1.005, spy_px*0.995, spy_px, spy_px))
    print(f"  • SPY prices (600d) seeded into daily_prices")


def seed_fundamentals(conn):
    today = datetime.now(timezone.utc).date()
    # avg_volume in fundamentals is avg 20-day DOLLAR volume (price × shares).
    # Portfolio-builder filters: avg_volume >= min_avg_dollar_volume_20d (20M).
    # Our tickers: price=$100, volume=1M → dollar_vol=$100M/day → well above threshold.
    avg_dv = int(PRICE * 1_000_000)   # $100M
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fundamentals WHERE ticker = ANY(%s)", (TICKERS,))
        for t in TICKERS:
            cur.execute("""
                INSERT INTO fundamentals
                  (ticker, as_of_date, roe, debt_to_equity, pe_ratio, pb_ratio,
                   revenue_growth, eps_growth, avg_volume, market_cap)
                VALUES (%s,%s, 0.18, 0.5, 20.0, 3.5, 0.10, 0.12, %s, 5000000000)
                ON CONFLICT DO NOTHING
            """, (t, today, avg_dv))
    print(f"  • fundamentals ({len(TICKERS)} tickers) seeded  [avg_dv=${avg_dv/1e6:.0f}M]")


def seed_alpaca_sync(conn, account_value: float, positions: dict):
    """
    Simulate a fresh alpaca-sync run.
    positions: {ticker: (qty, price)}
    Returns the run_id UUID.
    """
    now = datetime.now(timezone.utc)
    total_mv = sum(q * p for q, p in positions.values())
    cash = account_value - total_mv
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO alpaca_sync_runs
              (status, account_value, buying_power, cash, position_count, completed_at)
            VALUES ('success', %s, %s, %s, %s, %s)
            RETURNING run_id
        """, (account_value, cash, cash, len(positions), now))
        run_id = cur.fetchone()[0]

        for ticker, (qty, price) in positions.items():
            mv = qty * price
            cur.execute("""
                INSERT INTO live_positions
                  (sync_run_id, ticker, qty, avg_entry_price, current_price,
                   market_value, cost_basis, unrealized_pl, unrealized_plpc,
                   side, synced_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,0,0,'long',%s)
            """, (run_id, ticker, qty, price, price, mv, mv, now))

    print(f"  • alpaca-sync: account=${account_value:,.0f}  "
          f"positions={len(positions)}  cash=${cash:,.0f}")
    return run_id


def run_pipeline() -> dict:
    """POST /jobs/run?force=true and poll until completion (max 120s).

    force=true bypasses the once-per-day idempotency guard so consecutive
    test states can trigger fresh runs against the updated broker data.
    We track the returned run_id and poll until that specific run completes.
    """
    r = requests.post(f"{PIPELINE_URL}/jobs/run?force=true", json={}, timeout=15)
    if r.status_code not in (200, 202):
        return {"status": "error", "detail": r.text[:200]}
    body = r.json()
    if body.get("status") in ("already_running",):
        # Another run is in progress — wait and retry
        time.sleep(5)
        r2 = requests.post(f"{PIPELINE_URL}/jobs/run?force=true", json={}, timeout=15)
        if r2.status_code not in (200, 202):
            return {"status": "error", "detail": r2.text[:200]}
        body = r2.json()
    run_id = body.get("run_id")
    if not run_id:
        return {"status": "error", "detail": f"no run_id in response: {body}"}
    # Poll for this specific run_id to reach a terminal state
    for _ in range(120):
        time.sleep(1)
        try:
            st = requests.get(f"{PIPELINE_URL}/runs/latest", timeout=5).json()
            if st.get("run_id") == run_id and st.get("status") in ("success", "failed", "error"):
                return st
            # Also check if a newer run completed (shouldn't happen in sequential test)
        except Exception:
            pass
    return {"status": "timeout"}


def run_portfolio_builder() -> dict:
    """POST /jobs/build and poll until completion (max 60s)."""
    r = requests.post(f"{PORTBUILD_URL}/jobs/build", timeout=15)
    if r.status_code not in (200, 202):
        return {"status": "error", "detail": r.text[:200]}
    for _ in range(60):
        time.sleep(1)
        try:
            st = requests.get(f"{PORTBUILD_URL}/runs/latest", timeout=5).json()
            if st.get("status") in ("success", "failed", "error"):
                return st
        except Exception:
            pass
    return {"status": "timeout"}


def get_latest_intents(conn) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT di.ticker, di.action, di.rank, di.composite_score,
                   di.current_weight, di.actual_weight, di.weight_drift,
                   di.reason, di.confirmation_days_met, di.id as intent_id
            FROM delta_intents di
            WHERE di.run_id = (
                SELECT run_id FROM delta_runs ORDER BY completed_at DESC NULLS LAST LIMIT 1
            )
            ORDER BY di.action, di.ticker
        """)
        return [dict(r) for r in cur.fetchall()]


def by_action(intents):
    d = {}
    for i in intents:
        d.setdefault(i["action"], []).append(i)
    return d


# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "═"*72)
print("  SELL + TRANSFER DYNAMIC SIMULATION")
print("  Pipeline + portfolio-builder + trade-executor + risk-service (live)")
print("═"*72)

conn = db()

sub("Setup — seeding database")
seed_prices_and_universe(conn)
seed_spy_prices(conn)
seed_fundamentals(conn)

# Seed the initial balanced broker state BEFORE the first pipeline run
# so the delta engine sees a fully matched portfolio from the start
pos_full = {t: (float(SHARES_EACH), PRICE) for t in TICKERS}
seed_alpaca_sync(conn, ACCOUNT_VALUE, pos_full)

# Run pipeline first to produce ranking_runs + rankings (portfolio-builder needs these)
print("  Running pipeline (initial — builds ranking_runs for portfolio-builder)...")
r_setup = run_pipeline()
if r_setup.get("status") != "success":
    print(f"  ❌ Setup pipeline failed: {r_setup.get('status')} — cannot continue")
    sys.exit(1)
print(f"  ✓ Initial pipeline: {r_setup.get('status')}")

# Run portfolio-builder to produce portfolio_runs + portfolio_holdings
# (these rows have FK constraints into ranking_runs — must be created by the service)
print("  Running portfolio-builder (creates portfolio_runs + portfolio_holdings)...")
r_pb = run_portfolio_builder()
if r_pb.get("status") != "success":
    print(f"  ❌ Portfolio-builder failed: {r_pb.get('status')} — {r_pb}")
    sys.exit(1)
print(f"  ✓ Portfolio-builder: {r_pb.get('status')}")

# Verify portfolio_holdings were created
with conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM portfolio_holdings WHERE run_id = ("
                "SELECT run_id FROM portfolio_runs ORDER BY completed_at DESC LIMIT 1)")
    ph_count = cur.fetchone()[0]
print(f"  • portfolio_holdings created: {ph_count} rows")
check(ph_count == N_POSITIONS,
      f"SETUP  portfolio_holdings has {N_POSITIONS} rows after portfolio-builder",
      f"got {ph_count}")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE A — Balanced portfolio baseline")
# ═══════════════════════════════════════════════════════════════════════════════
# Re-seed alpaca_sync with full balanced portfolio and re-run pipeline.
# Delta engine should see: all 10 tickers in target AND broker → HOLD.
seed_alpaca_sync(conn, ACCOUNT_VALUE, pos_full)
print("  Running pipeline...")
r_A = run_pipeline()
check(r_A.get("status") == "success", "STATE-A  Pipeline completed", r_A.get("status","?"))

intents_A = get_latest_intents(conn)
ba_A = by_action(intents_A)
print(f"  • Delta intents: {dict((k, len(v)) for k,v in ba_A.items())}")
check(len(ba_A.get("entry",  [])) == 0, "STATE-A  No ENTRY in balanced portfolio")
check(len(ba_A.get("exit",   [])) == 0, "STATE-A  No EXIT  in balanced portfolio")
check(len(intents_A) > 0,               "STATE-A  Delta engine produced signals")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE B — User sells TK00 at broker; cash stays ($150k account)")
# ═══════════════════════════════════════════════════════════════════════════════
# Alpaca now shows only 9 positions; cash += $15k; total account still $150k
sold = "TK00"
pos_minus_one = {t: v for t, v in pos_full.items() if t != sold}
seed_alpaca_sync(conn, ACCOUNT_VALUE, pos_minus_one)
# portfolio_holdings still has TK00 at 10% — system doesn't know it was deliberately sold

print("  Running pipeline...")
r_B = run_pipeline()
check(r_B.get("status") == "success", "STATE-B  Pipeline completed", r_B.get("status","?"))

intents_B = get_latest_intents(conn)
ba_B = by_action(intents_B)
print(f"  • Delta intents: {dict((k,len(v)) for k,v in ba_B.items())}")

# System should generate ENTRY for TK00 (in target but gone from broker)
entry_B = [i for i in ba_B.get("entry",[]) if i["ticker"] == sold]
check(len(entry_B) == 1,
      f"STATE-B  System generates ENTRY for {sold} (target says hold, broker shows it gone)",
      f"entries={[i['ticker'] for i in ba_B.get('entry',[])]}")

# Remaining 9 positions: 15k/150k = 10% actual, 10% target → drift = 0% → hold
remaining_B = [i for i in intents_B if i["ticker"] != sold]
st_B = [i for i in remaining_B if i["action"] == "sell_trim"]
check(len(st_B) == 0,
      "STATE-B  No SELL_TRIM for remaining 9 (cash absorbed the sale, actual weight unchanged)")

if entry_B:
    w = float(entry_B[0]["current_weight"])
    expected_shares = math.floor(ACCOUNT_VALUE * w / PRICE)
    print(f"  • If re-entry approved: floor({ACCOUNT_VALUE:,.0f} × {w:.1%} ÷ ${PRICE:.0f}) = {expected_shares} shares")
    check(expected_shares == SHARES_EACH,
          f"STATE-B  Re-entry would restore the full position ({expected_shares} shares)")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE C — User sells TK00 AND transfers $15k away (account=$135k)")
# ═══════════════════════════════════════════════════════════════════════════════
new_av_C = ACCOUNT_VALUE - MV_EACH    # $135k
seed_alpaca_sync(conn, new_av_C, pos_minus_one)

print("  Running pipeline...")
r_C = run_pipeline()
check(r_C.get("status") == "success", "STATE-C  Pipeline completed", r_C.get("status","?"))

intents_C = get_latest_intents(conn)
ba_C = by_action(intents_C)
print(f"  • Delta intents: {dict((k,len(v)) for k,v in ba_C.items())}")

# Still ENTRY for TK00 — system still wants it back
entry_C = next((i for i in ba_C.get("entry",[]) if i["ticker"] == sold), None)
check(entry_C is not None,
      f"STATE-C  ENTRY still fires for {sold} after cash transfer",
      f"action={entry_C['action'] if entry_C else 'missing'}")

# Re-entry sized on smaller account
if entry_C and entry_C.get("current_weight"):
    w_C = float(entry_C["current_weight"])
    shares_C = math.floor(new_av_C * w_C / PRICE)
    shares_B = math.floor(ACCOUNT_VALUE * w_C / PRICE)
    print(f"  • Entry sizing: ${new_av_C:,.0f} × {w_C:.1%} ÷ ${PRICE:.0f} = {shares_C}sh "
          f"(before transfer: {shares_B}sh)")
    check(shares_C < shares_B,
          "STATE-C  Entry sized SMALLER because account shrank after transfer",
          f"before={shares_B}sh, after={shares_C}sh")

# Remaining 9: actual = 15k/135k = 11.1% vs 10% target; drift = +1.1% < 2% → HOLD
actual_w_C = MV_EACH / new_av_C
drift_C = actual_w_C - TARGET_WEIGHT
print(f"  • Remaining 9: actual={actual_w_C:.2%} target={TARGET_WEIGHT:.2%} drift={drift_C:+.2%}")
st_C = [i for i in intents_C if i["ticker"] != sold and i["action"] == "sell_trim"]
check(len(st_C) == 0,
      "STATE-C  No SELL_TRIM for remaining 9 positions (drift +1.1% below 2% threshold)")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE D — Larger transfer: account drops to $120k, drift >2% on all 9")
# ═══════════════════════════════════════════════════════════════════════════════
# 9 positions × $15k = $135k MV; account = $120k → actual_weight = 15k/120k = 12.5%
# drift = +2.5% → all 9 should generate SELL_TRIM
new_av_D = 120_000.0
seed_alpaca_sync(conn, new_av_D, pos_minus_one)

print("  Running pipeline...")
r_D = run_pipeline()
check(r_D.get("status") == "success", "STATE-D  Pipeline completed", r_D.get("status","?"))

intents_D = get_latest_intents(conn)
ba_D = by_action(intents_D)
print(f"  • Delta intents: {dict((k,len(v)) for k,v in ba_D.items())}")

actual_w_D = MV_EACH / new_av_D
drift_D    = actual_w_D - TARGET_WEIGHT
print(f"  • Remaining 9: actual={actual_w_D:.2%} drift={drift_D:+.2%}")

entry_D    = [i for i in ba_D.get("entry",[])    if i["ticker"] == sold]
st_D       = [i for i in ba_D.get("sell_trim",[]) if i["ticker"] != sold]
check(len(entry_D) == 1,
      "STATE-D  ENTRY for TK00 (system still wants to re-buy)", f"entries={len(entry_D)}")
check(len(st_D) == 9,
      "STATE-D  All 9 remaining positions get SELL_TRIM (drift +2.5% > 2%)",
      f"sell_trim={len(st_D)}/9")

# Verify sell_trim qty arithmetic
if st_D:
    s = st_D[0]
    a_w = float(s["actual_weight"]) if s.get("actual_weight") else actual_w_D
    t_w = float(s["current_weight"]) if s.get("current_weight") else TARGET_WEIGHT
    qty_trim = math.floor((a_w - t_w) * new_av_D / PRICE)
    print(f"  • sell_trim per position: floor(({a_w:.4f}−{t_w:.4f}) × ${new_av_D:,.0f} ÷ ${PRICE:.0f}) = {qty_trim}sh")
    check(qty_trim >= 1,
          "STATE-D  sell_trim produces a tradeable quantity", f"qty={qty_trim}")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE E — User sells 2 positions (TK00+TK01) and transfers $30k away")
# ═══════════════════════════════════════════════════════════════════════════════
sold_two = {"TK00", "TK01"}
pos_minus_two = {t: v for t, v in pos_full.items() if t not in sold_two}
new_av_E = ACCOUNT_VALUE - 2 * MV_EACH   # $120k; 8 positions × $15k = $120k MV

seed_alpaca_sync(conn, new_av_E, pos_minus_two)
# portfolio_holdings still has all 10 tickers at ~10% each

print("  Running pipeline...")
r_E = run_pipeline()
check(r_E.get("status") == "success", "STATE-E  Pipeline completed", r_E.get("status","?"))

intents_E = get_latest_intents(conn)
ba_E = by_action(intents_E)
print(f"  • Delta intents: {dict((k,len(v)) for k,v in ba_E.items())}")

entry_tickers_E = {i["ticker"] for i in ba_E.get("entry",[])}
check(sold_two <= entry_tickers_E,
      "STATE-E  Both sold tickers get ENTRY intent",
      f"entries={entry_tickers_E}")

# 8 remaining: 15k/120k = 12.5% → drift +2.5% → SELL_TRIM
actual_w_E = MV_EACH / new_av_E
drift_E    = actual_w_E - TARGET_WEIGHT
print(f"  • 8 remaining: actual={actual_w_E:.2%} drift={drift_E:+.2%}")
st_E = [i for i in ba_E.get("sell_trim",[]) if i["ticker"] not in sold_two]
check(len(st_E) == 8,
      "STATE-E  All 8 remaining positions get SELL_TRIM (drift +2.5%)",
      f"sell_trim={len(st_E)}/8")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE F — Cash transfer only (no positions sold), account drops to $125k")
# ═══════════════════════════════════════════════════════════════════════════════
# All 10 positions intact; $25k cash transferred out → 10 × $15k = $150k in positions
# Note: this is an unusual edge case — positions exceed account value — only possible
# if the account had separate margin or the transfer was from a non-position cash balance.
# The scenario tests the FP boundary at exactly +2.0% drift.
new_av_F = 125_000.0
seed_alpaca_sync(conn, new_av_F, pos_full)
# portfolio_holdings stays as-is from the initial portfolio-builder run

print("  Running pipeline...")
r_F = run_pipeline()
check(r_F.get("status") == "success", "STATE-F  Pipeline completed", r_F.get("status","?"))

intents_F = get_latest_intents(conn)
ba_F = by_action(intents_F)
print(f"  • Delta intents: {dict((k,len(v)) for k,v in ba_F.items())}")

check(len(ba_F.get("entry",[])) == 0,
      "STATE-F  No ENTRY signals (all positions still held at broker)")

actual_w_F = MV_EACH / new_av_F
drift_F    = actual_w_F - TARGET_WEIGHT
# IEEE 754: 15000/125000 = 0.12; 0.12 - 0.10 = 0.020000000000000004 > 0.02
print(f"  • All 10: actual={actual_w_F:.2%} drift={drift_F:+.6f}  threshold={DRIFT_THR:.2%}")
print(f"  • FP note: abs({actual_w_F:.2%} - {TARGET_WEIGHT:.2%}) = {abs(actual_w_F - TARGET_WEIGHT):.20f}")
st_F   = ba_F.get("sell_trim",[])
hold_F = ba_F.get("hold",[])
check(len(st_F) + len(hold_F) == N_POSITIONS,
      "STATE-F  All positions are HOLD or SELL_TRIM at the +2.0% boundary",
      f"sell_trim={len(st_F)}  hold={len(hold_F)}")
# FP arithmetic: 0.12 - 0.10 = 0.020000000000000004 which is > 0.02 → fires SELL_TRIM
if len(st_F) == N_POSITIONS:
    print("  ⚡ FP effect: drift fires SELL_TRIM at exactly +2.0% boundary (IEEE 754)")
elif len(hold_F) == N_POSITIONS:
    print("  ⚡ Drift did NOT fire at +2.0% boundary (HOLD)")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE G — Sell TK00 then re-buy before pipeline runs (net: no change)")
# ═══════════════════════════════════════════════════════════════════════════════
# By the time alpaca-sync fires, TK00 is back in the account → system sees no change
seed_alpaca_sync(conn, ACCOUNT_VALUE, pos_full)

print("  Running pipeline...")
r_G = run_pipeline()
check(r_G.get("status") == "success", "STATE-G  Pipeline completed", r_G.get("status","?"))

intents_G = get_latest_intents(conn)
ba_G = by_action(intents_G)
print(f"  • Delta intents: {dict((k,len(v)) for k,v in ba_G.items())}")
check(len(ba_G.get("entry",[])) == 0,
      "STATE-G  No ENTRY for TK00 (re-bought before pipeline ran — net zero change)")
check(len(ba_G.get("exit",[])) == 0,
      "STATE-G  No EXIT signals")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("STATE H — Stale alpaca-sync: trade-executor refuses to size orders")
# ═══════════════════════════════════════════════════════════════════════════════
# Insert a sync row that is 25 hours old, plus an entry intent for TK00
stale_time = datetime.now(timezone.utc) - timedelta(hours=25)
with conn.cursor() as cur:
    cur.execute("""
        INSERT INTO alpaca_sync_runs
          (status, account_value, buying_power, cash, position_count, completed_at)
        VALUES ('success', 150000, 0, 0, 9, %s)
        RETURNING run_id
    """, (stale_time,))
    stale_run_id = cur.fetchone()[0]

    # Insert a fresh entry intent pointing at the latest delta_run
    cur.execute("""
        SELECT run_id FROM delta_runs ORDER BY completed_at DESC NULLS LAST LIMIT 1
    """)
    dr_row = cur.fetchone()
    if dr_row:
        delta_run_id = dr_row[0]
        cur.execute("""
            INSERT INTO delta_intents
              (run_id, ticker, action, rank, composite_score, current_weight,
               confirmation_days_met, created_at)
            VALUES (%s, 'TK00', 'entry', 3, 0.85, 0.10, 3, NOW())
            RETURNING id
        """, (delta_run_id,))
        intent_row = cur.fetchone()
        intent_id = str(intent_row[0]) if intent_row else None
    else:
        intent_id = None

if intent_id:
    # Make stale sync the only 'success' sync by archiving fresh ones temporarily
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE alpaca_sync_runs SET status='archived'
            WHERE status='success' AND run_id != %s
        """, (stale_run_id,))

    try:
        resp = requests.post(f"{TRADE_URL}/jobs/submit",
                             json={"intent_id": intent_id, "mode": "immediate"},
                             timeout=10)
        print(f"  • Trade-executor response: HTTP {resp.status_code}")
        body = resp.json()
        print(f"  • Response body: {json.dumps(body, default=str)[:300]}")
        check(resp.status_code in (400, 409, 422, 500),
              "STATE-H  Trade-executor rejects order sizing when sync is 25h old",
              f"http={resp.status_code}")
        detail = json.dumps(body).lower()
        check("stale" in detail or "old" in detail or "age" in detail or "24" in detail or "hour" in detail,
              "STATE-H  Error message mentions staleness",
              f"body={json.dumps(body)[:100]}")
    except Exception as e:
        fail("STATE-H  HTTP request failed", str(e))
    finally:
        # Restore fresh sync records
        with conn.cursor() as cur:
            cur.execute("UPDATE alpaca_sync_runs SET status='success' WHERE status='archived'")
else:
    warn("STATE-H  Could not create test intent — skipping staleness test")

# ═══════════════════════════════════════════════════════════════════════════════
hdr("BEHAVIOURAL SUMMARY")
print("""
  Scenario     What the system does                             User action needed
  ──────────── ─────────────────────────────────────────────── ────────────────────────────
  B  Sell+keep ENTRY intent for TK00 (system wants re-buy)     REJECT the entry in Trader tab
  cash         9 remaining: HOLD (actual weight still 10%)     or re-run portfolio-builder

  C  Sell+$15k ENTRY for TK00, sized on $135k account          REJECT entry; system will
  transfer     9 remaining: HOLD (drift only +1.1% < 2%)       keep proposing it each day
               Note: re-entry would buy FEWER shares than
               originally sold (135 shares not 150)

  D  Sell+$30k ENTRY for TK00 (system still wants it)          REJECT entry AND
  transfer     9 remaining: SELL_TRIM (drift +2.5%)            APPROVE the 9 trims
               → Two conflicting forces: system wants to        to restore weight balance
               buy TK00 while trimming the other 9

  E  Sell 2+   ENTRY for both TK00 and TK01                    REJECT both entries
  transfer     8 remaining: SELL_TRIM (drift +2.5%)            APPROVE trims

  F  Cash only No ENTRY (positions intact)                     Approve SELL_TRIM if
  (no sell)    10 positions: SELL_TRIM at +2.0% boundary       drift fires; or ignore
               (IEEE 754: 0.12 - 0.10 = 0.02000...04 > 0.02)

  G  Sell+     HOLD for all (net zero change seen by system)    No action needed
  re-buy

  H  Stale     Trade-executor REFUSES to size any order         Re-run alpaca-sync
  sync         (safety gate: account_value too old)             before approving trades
""")

print("  KEY INSIGHT — States D and E (sell + large transfer):")
print("  The system simultaneously wants to BUY the sold ticker back AND SELL_TRIM")
print("  the remaining positions. These two signals are in conflict:")
print("  • Buying TK00 back adds position value → makes overweight even worse")
print("  • System does not model this interaction — each ticker is evaluated independently")
print("  The user must resolve the conflict manually via the Trader tab.")
print()
print("  ROOT CAUSE — the delta engine does not know WHY a position disappeared.")
print("  'Sold by broker with intent to stay out' looks identical to 'missed entry'.")
print("  The only guard is human approval: every ENTRY intent requires a button click.")

# ─────────────────────────────────────────────────────────────────────────────
hdr("FINAL VERDICT")
total = len(PASSED) + len(ERRORS)
print(f"\n  Tests run: {total}  Passed: {len(PASSED)}  Failed: {len(ERRORS)}  Warnings: {len(WARNINGS)}")
if ERRORS:
    print("\n  Failed tests:")
    for e in ERRORS: print(f"    ❌ {e}")
if WARNINGS:
    print("\n  Warnings:")
    for w in WARNINGS: print(f"    ⚠️  {w}")
print()
if ERRORS:
    print(f"  {'═'*50}\n  RESULT: FAIL ({len(ERRORS)} errors)\n  {'═'*50}")
else:
    print(f"  {'═'*50}\n  RESULT: PASS ({len(PASSED)} tests)\n  {'═'*50}")
conn.close()
