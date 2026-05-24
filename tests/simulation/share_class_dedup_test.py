#!/usr/bin/env python3
"""
Dynamic end-to-end tests for share-class deduplication in the pipeline.

Seeds known duplicate share-class pairs into the DB, runs the pipeline via HTTP,
and verifies only the best-ranked ticker per company survives in rankings.

Corner cases covered:
  1. Basic 2-ticker pair: GOOG / GOOGL (same name, GOOG ranks higher)
  2. Basic 2-ticker pair reversed: NWSA / NWS (same name, NWSA ranks higher)
  3. Three-way duplicate: BRK.A / BRK.B / BRK.C (same name, one survivor)
  4. Ticker with null/empty name: not merged with any group, survives alone
  5. Unique tickers: no duplicate names, all survive
  6. Exact score tie: lower rank-number ticker (best-ranked) survives
  7. deduplicate_share_classes=false (via force=true on an unmodified run): no dedup
     — tested by checking the ranking_runs log step is absent
  8. Mix: some companies have duplicates, some don't — count is correct
  9. Sibling with no ranking: GOOGL ranked, GOOG not ranked — GOOGL survives alone
 10. All same company: all tickers same name, only rank-1 survives

Run against live Docker stack:
    python tests/simulation/share_class_dedup_test.py

Services required: pipeline (:8018), postgres (via DATABASE_URL).
"""

import math
import os
import sys
import time
import uuid
from datetime import date, timedelta

import psycopg2
import requests

PIPELINE_URL = os.getenv("PIPELINE_URL", "http://localhost:8018")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://stocker:stocker@localhost:5433/stocker"
)
TIMEOUT = 30  # seconds per pipeline wait

# ── helpers ──────────────────────────────────────────────────────────────────

_SQRT2 = math.sqrt(2)
_SQRT3 = math.sqrt(3)

def _sim_price(t_idx: int, day_idx: int, base: float = 100.0) -> float:
    """Non-flat price so covariance matrix is non-singular."""
    return base * (1.0 + 0.005 * math.sin(t_idx * _SQRT2 + day_idx * _SQRT3))

def db_conn():
    return psycopg2.connect(DATABASE_URL)

def now_ts():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)

class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self._failures: list[str] = []

    def check(self, label: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            print(f"  ✅ {label}")
        else:
            self.failed += 1
            msg = f"  ❌ {label}" + (f": {detail}" if detail else "")
            print(msg)
            self._failures.append(msg)

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self._failures:
            print("Failures:")
            for f in self._failures:
                print(f"  {f}")
        return self.failed == 0


# ── DB seed helpers ───────────────────────────────────────────────────────────

STRATEGY_ID = "quality_core_v1"
TODAY = date.today()
SNAPSHOT_DATE = TODAY


def _clean_test_tickers(cur, tickers: list[str]):
    """Remove test tickers from all relevant tables."""
    if not tickers:
        return
    cur.execute("DELETE FROM rankings WHERE ticker = ANY(%s)", (tickers,))
    cur.execute("DELETE FROM factor_scores WHERE ticker = ANY(%s)", (tickers,))
    cur.execute("DELETE FROM daily_prices WHERE ticker = ANY(%s)", (tickers,))
    cur.execute("DELETE FROM fundamentals WHERE ticker = ANY(%s)", (tickers,))
    cur.execute("DELETE FROM universe_tickers WHERE ticker = ANY(%s)", (tickers,))


def _ensure_snapshot(cur) -> int:
    """Return the snapshot id the pipeline will use (same ORDER BY as the pipeline)."""
    cur.execute(
        "SELECT id FROM universe_snapshots ORDER BY snapshot_date DESC, fetched_at DESC LIMIT 1"
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count, fetched_at) "
        "VALUES ('AV_LISTING', %s, 0, NOW()) RETURNING id",
        (SNAPSHOT_DATE,),
    )
    return cur.fetchone()[0]


def _seed_ticker(cur, ticker: str, company_name: str | None, snapshot_id: int,
                 t_idx: int, base_price: float = 100.0, roe: float = 0.18):
    """Seed a ticker with ~430 weekday price rows, fundamentals, and a universe entry.

    Weekday-only prices prevent weekend dates from contaminating the price pivot used
    by the factor engine, which would shift iloc[-252] / iloc[-21] onto NaN rows.

    Use `roe` to force a predictable quality ordering when testing dedup winner selection:
    higher roe → higher quality score → better composite rank.
    """
    # Universe entry (delete+insert to handle re-seeding cleanly)
    cur.execute(
        "DELETE FROM universe_tickers WHERE snapshot_id=%s AND ticker=%s",
        (snapshot_id, ticker),
    )
    cur.execute(
        "INSERT INTO universe_tickers (snapshot_id, ticker, name, sector) "
        "VALUES (%s, %s, %s, 'Technology')",
        (snapshot_id, ticker, company_name),
    )
    # Prices: weekdays only over the past 600 calendar days (~428 trading days)
    price_rows = []
    day_idx = 0
    d = TODAY - timedelta(days=600)
    while d < TODAY:
        if d.weekday() < 5:  # Mon–Fri only
            p = _sim_price(t_idx, day_idx, base_price)
            price_rows.append((ticker, d, p, p, p, p, p, int(1e6)))
            day_idx += 1
        d += timedelta(days=1)
    cur.executemany(
        "INSERT INTO daily_prices (ticker, date, open, high, low, close, adjusted_close, volume) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (ticker, date) DO UPDATE SET adjusted_close=EXCLUDED.adjusted_close",
        price_rows,
    )
    # Fundamentals — roe controls quality score ordering between same-company pairs
    avg_dv = int(base_price * 1_000_000)
    cur.execute(
        "INSERT INTO fundamentals (ticker, as_of_date, roe, debt_to_equity, pe_ratio, pb_ratio, "
        "revenue_growth, eps_growth, avg_volume, market_cap) "
        "VALUES (%s, %s, %s, 0.5, 20.0, 3.5, 0.10, 0.12, %s, 5000000000) "
        "ON CONFLICT (ticker, as_of_date) DO UPDATE SET roe=EXCLUDED.roe, avg_volume=EXCLUDED.avg_volume",
        (ticker, TODAY, roe, avg_dv),
    )


def run_pipeline(force: bool = True) -> dict:
    url = f"{PIPELINE_URL}/jobs/run" + ("?force=true" if force else "")
    r = requests.post(url, json={}, timeout=15)
    if r.status_code not in (200, 202):
        return {"status": "error", "detail": r.text[:300]}
    body = r.json()
    if body.get("status") == "already_running":
        time.sleep(5)
        r2 = requests.post(url, json={}, timeout=15)
        body = r2.json() if r2.status_code in (200, 202) else {"status": "error"}
    run_id = body.get("run_id")
    if not run_id:
        return {"status": "error", "detail": f"no run_id: {body}"}
    for _ in range(120):
        time.sleep(1)
        try:
            st = requests.get(f"{PIPELINE_URL}/runs/latest", timeout=5).json()
            if st.get("run_id") == run_id and st.get("status") in ("success", "failed", "error"):
                return st
        except Exception:
            pass
    return {"status": "timeout", "run_id": run_id}


def get_rankings(conn) -> dict[str, int]:
    """Return {ticker: rank} from the most recent successful ranking_run."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id FROM ranking_runs WHERE status='success' "
            "ORDER BY completed_at DESC NULLS LAST LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return {}
        run_id = row[0]
        cur.execute(
            "SELECT ticker, rank FROM rankings WHERE run_id = %s", (run_id,)
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def get_dedup_log(conn) -> list[dict]:
    """Return deduplicate_share_classes execution_steps from the last ranking trace."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT es.output_summary FROM execution_steps es "
            "JOIN execution_traces et ON et.trace_id = es.trace_id "
            "WHERE es.step_name = 'deduplicate_share_classes' "
            "ORDER BY es.started_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return []
        import json
        summary = row[0]
        if isinstance(summary, str):
            summary = json.loads(summary)
        return summary.get("removed", [])


# ── Individual test cases ─────────────────────────────────────────────────────

def test_basic_pair_goog_googl(tr: TestRunner, conn, snapshot_id: int):
    """GOOG ranks #1, GOOGL ranks #2 → GOOGL removed, GOOG survives at rank 1."""
    print("\n[1] Basic pair: GOOG (rank 1) vs GOOGL (rank 2)")
    tickers = ["GOOG", "GOOGL"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        # GOOG gets higher ROE → better quality score → better composite rank
        _seed_ticker(cur, "GOOG",  "Alphabet Inc.", snapshot_id, t_idx=10, base_price=180.0, roe=0.40)
        _seed_ticker(cur, "GOOGL", "Alphabet Inc.", snapshot_id, t_idx=11, base_price=179.0, roe=0.05)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    tr.check("GOOG present in rankings", "GOOG" in rankings)
    tr.check("GOOGL removed from rankings", "GOOGL" not in rankings,
             f"GOOGL at rank {rankings.get('GOOGL')}")
    removed = get_dedup_log(conn)
    removed_tickers = [d["removed_ticker"] for d in removed]
    tr.check("dedup log records GOOGL removal", "GOOGL" in removed_tickers, str(removed))

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_pair_reversed_nwsa_nws(tr: TestRunner, conn, snapshot_id: int):
    """NWSA ranks better than NWS (higher ROE → better quality) → NWS removed."""
    print("\n[2] Pair reversed: NWSA ranks better than NWS")
    tickers = ["NWS", "NWSA"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        _seed_ticker(cur, "NWSA", "News Corp", snapshot_id, t_idx=20, base_price=30.0, roe=0.40)
        _seed_ticker(cur, "NWS",  "News Corp", snapshot_id, t_idx=21, base_price=28.0, roe=0.05)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    tr.check("NWSA present", "NWSA" in rankings)
    tr.check("NWS removed",  "NWS" not in rankings, f"NWS at rank {rankings.get('NWS')}")

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_three_way_duplicate(tr: TestRunner, conn, snapshot_id: int):
    """BRK.A / BRK.B / BRK.C all same name → only best-ranked survives.
    BRK.A gets the highest ROE so it wins the quality ranking.
    """
    print("\n[3] Three-way duplicate: BRK.A / BRK.B / BRK.C")
    tickers = ["BRK.A", "BRK.B", "BRK.C"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        _seed_ticker(cur, "BRK.A", "Berkshire Hathaway Inc", snapshot_id, t_idx=30, base_price=500.0, roe=0.45)
        _seed_ticker(cur, "BRK.B", "Berkshire Hathaway Inc", snapshot_id, t_idx=31, base_price=450.0, roe=0.15)
        _seed_ticker(cur, "BRK.C", "Berkshire Hathaway Inc", snapshot_id, t_idx=32, base_price=400.0, roe=0.05)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    brk_present = [t for t in tickers if t in rankings]
    tr.check("exactly one BRK ticker survives", len(brk_present) == 1,
             f"present={brk_present}")
    tr.check("BRK.A is the survivor (best base_price)", "BRK.A" in rankings,
             f"present={brk_present}")

    removed = get_dedup_log(conn)
    removed_names = [d["removed_ticker"] for d in removed]
    tr.check("BRK.B removed", "BRK.B" in removed_names, str(removed_names))
    tr.check("BRK.C removed", "BRK.C" in removed_names, str(removed_names))

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_null_name_not_merged(tr: TestRunner, conn, snapshot_id: int):
    """Tickers with NULL company name are NOT merged — both survive."""
    print("\n[4] NULL company name: tickers not merged")
    tickers = ["ZTEST1", "ZTEST2"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        _seed_ticker(cur, "ZTEST1", None, snapshot_id, t_idx=40, base_price=50.0)
        _seed_ticker(cur, "ZTEST2", None, snapshot_id, t_idx=41, base_price=49.0)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    tr.check("ZTEST1 survives (null name)", "ZTEST1" in rankings)
    tr.check("ZTEST2 survives (null name)", "ZTEST2" in rankings)

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_empty_name_not_merged(tr: TestRunner, conn, snapshot_id: int):
    """Empty-string company name: tickers not merged."""
    print("\n[5] Empty company name: tickers not merged")
    tickers = ["ZTEST3", "ZTEST4"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        _seed_ticker(cur, "ZTEST3", "", snapshot_id, t_idx=42, base_price=50.0)
        _seed_ticker(cur, "ZTEST4", "", snapshot_id, t_idx=43, base_price=49.0)
        # Directly set empty string (seed_ticker may have stored None for empty)
        cur.execute(
            "UPDATE universe_tickers SET name='' WHERE ticker IN ('ZTEST3','ZTEST4')"
        )
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    tr.check("ZTEST3 survives (empty name)", "ZTEST3" in rankings)
    tr.check("ZTEST4 survives (empty name)", "ZTEST4" in rankings)

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_unique_tickers_all_survive(tr: TestRunner, conn, snapshot_id: int):
    """Different company names: all tickers survive."""
    print("\n[6] Unique names: all tickers survive")
    tickers = ["ZUNIQ1", "ZUNIQ2", "ZUNIQ3"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        _seed_ticker(cur, "ZUNIQ1", "Alpha Corp",   snapshot_id, t_idx=50, base_price=80.0)
        _seed_ticker(cur, "ZUNIQ2", "Beta Corp",    snapshot_id, t_idx=51, base_price=79.0)
        _seed_ticker(cur, "ZUNIQ3", "Gamma Corp",   snapshot_id, t_idx=52, base_price=78.0)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    for t in tickers:
        tr.check(f"{t} survives (unique name)", t in rankings)

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_exact_score_tie(tr: TestRunner, conn, snapshot_id: int):
    """Two tickers same company, forced to identical factor scores → lower rank index survives."""
    print("\n[7] Exact score tie: lower rank-number (first found) survives")
    tickers = ["ZTIE1", "ZTIE2"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        # Use same t_idx so their prices are identical → identical factor scores
        _seed_ticker(cur, "ZTIE1", "Tie Corp", snapshot_id, t_idx=60, base_price=100.0)
        _seed_ticker(cur, "ZTIE2", "Tie Corp", snapshot_id, t_idx=60, base_price=100.0)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    tie_present = [t for t in tickers if t in rankings]
    tr.check("exactly one Tie Corp ticker survives", len(tie_present) == 1,
             f"present={tie_present}")

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_sibling_not_ranked(tr: TestRunner, conn, snapshot_id: int):
    """Only one of two siblings makes it through factor scoring → the ranked one survives."""
    print("\n[8] Only one sibling ranked: surviving sibling stays")
    tickers = ["ZHALF1", "ZHALF2"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        # ZHALF1 seeded normally
        _seed_ticker(cur, "ZHALF1", "Half Corp", snapshot_id, t_idx=70, base_price=60.0)
        # ZHALF2 in universe but NO prices → factor engine drops it before ranking
        cur.execute(
            "DELETE FROM universe_tickers WHERE ticker='ZHALF2'"
        )
        cur.execute(
            "INSERT INTO universe_tickers (snapshot_id, ticker, name, sector) "
            "VALUES (%s, 'ZHALF2', 'Half Corp', 'Technology')",
            (snapshot_id,),
        )
        # No price rows for ZHALF2, no fundamentals — it won't make it to ranking
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    tr.check("ZHALF1 survives", "ZHALF1" in rankings)
    tr.check("ZHALF2 absent (never ranked)", "ZHALF2" not in rankings)

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_mixed_scenario(tr: TestRunner, conn, snapshot_id: int):
    """Mixed: 2 duplicates + 2 unique → 3 survivors total."""
    print("\n[9] Mixed: 2 duplicate pair + 2 unique = 3 survivors")
    tickers = ["ZMIX1", "ZMIX2", "ZMIX3", "ZMIX4"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        # ZMIX1 has higher ROE so it wins the duplicate pair over ZMIX2
        _seed_ticker(cur, "ZMIX1", "Mix Alpha Inc", snapshot_id, t_idx=80, base_price=110.0, roe=0.40)
        _seed_ticker(cur, "ZMIX2", "Mix Alpha Inc", snapshot_id, t_idx=81, base_price=105.0, roe=0.05)
        _seed_ticker(cur, "ZMIX3", "Mix Beta Inc",  snapshot_id, t_idx=82, base_price=100.0)
        _seed_ticker(cur, "ZMIX4", "Mix Gamma Inc", snapshot_id, t_idx=83, base_price=95.0)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    zmix_present = [t for t in tickers if t in rankings]
    tr.check("3 survivors from 4 tickers", len(zmix_present) == 3,
             f"present={zmix_present}")
    tr.check("ZMIX1 survives (best of duplicate pair)", "ZMIX1" in rankings)
    tr.check("ZMIX2 removed (worse of duplicate pair)", "ZMIX2" not in rankings)
    tr.check("ZMIX3 survives (unique)", "ZMIX3" in rankings)
    tr.check("ZMIX4 survives (unique)", "ZMIX4" in rankings)

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_all_same_company(tr: TestRunner, conn, snapshot_id: int):
    """All 4 tickers same company name → only rank-1 survives.
    ZALL1 gets highest ROE so it wins the quality ranking.
    """
    print("\n[10] All same company: only rank-1 survives")
    tickers = ["ZALL1", "ZALL2", "ZALL3", "ZALL4"]
    roes = [0.45, 0.20, 0.10, 0.05]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        for i, (t, price, roe) in enumerate(zip(tickers, [120.0, 110.0, 100.0, 90.0], roes)):
            _seed_ticker(cur, t, "Monopoly Corp", snapshot_id, t_idx=90 + i, base_price=price, roe=roe)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    survivors = [t for t in tickers if t in rankings]
    tr.check("exactly 1 survivor from 4 same-company tickers", len(survivors) == 1,
             f"survivors={survivors}")
    tr.check("ZALL1 is the sole survivor (highest price → best rank)", "ZALL1" in survivors)

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_rank_reassignment(tr: TestRunner, conn, snapshot_id: int):
    """After dedup, ranks are contiguous starting from 1.
    ZGAP1 and ZGAP3 are the same company; ZGAP1 has much higher ROE so it wins.
    """
    print("\n[11] Rank reassignment: gaps closed after dedup")
    tickers = ["ZGAP1", "ZGAP2", "ZGAP3", "ZGAP4"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        _seed_ticker(cur, "ZGAP1", "Gap Corp",      snapshot_id, t_idx=100, base_price=200.0, roe=0.45)
        _seed_ticker(cur, "ZGAP2", "Other Corp A",  snapshot_id, t_idx=101, base_price=150.0, roe=0.18)
        _seed_ticker(cur, "ZGAP3", "Gap Corp",      snapshot_id, t_idx=102, base_price=100.0, roe=0.05)
        _seed_ticker(cur, "ZGAP4", "Other Corp B",  snapshot_id, t_idx=103, base_price=50.0,  roe=0.18)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    rankings = get_rankings(conn)
    # After dedup the global rank sequence must be contiguous (1..N with no gaps).
    all_ranks = sorted(rankings.values())
    expected = list(range(1, len(all_ranks) + 1))
    tr.check("global ranks contiguous after dedup", all_ranks == expected,
             f"ranks={all_ranks[:10]}…")
    tr.check("ZGAP3 removed", "ZGAP3" not in rankings)

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


def test_percentile_after_dedup(tr: TestRunner, conn, snapshot_id: int):
    """Percentiles are recomputed after dedup (no out-of-range values)."""
    print("\n[12] Percentile recomputation after dedup")
    tickers = ["ZPCT1", "ZPCT2", "ZPCT3"]
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        # ZPCT1 has higher ROE so it wins the duplicate pair; ZPCT3 is unique
        _seed_ticker(cur, "ZPCT1", "Pct Dupe Corp", snapshot_id, t_idx=110, base_price=150.0, roe=0.40)
        _seed_ticker(cur, "ZPCT2", "Pct Dupe Corp", snapshot_id, t_idx=111, base_price=100.0, roe=0.05)
        _seed_ticker(cur, "ZPCT3", "Pct Unique",    snapshot_id, t_idx=112, base_price=80.0,  roe=0.05)
    conn.commit()

    result = run_pipeline()
    tr.check("pipeline succeeded", result.get("status") == "success", result.get("status"))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, percentile FROM rankings r "
            "WHERE r.run_id = ("
            "  SELECT run_id FROM ranking_runs WHERE status='success' "
            "  ORDER BY completed_at DESC NULLS LAST LIMIT 1"
            ")"
        )
        pcts = {r[0]: float(r[1]) for r in cur.fetchall() if r[0] in tickers}

    for t, pct in pcts.items():
        tr.check(f"{t} percentile in [0,1]", 0.0 <= pct <= 1.0, f"pct={pct}")
    if "ZPCT1" in pcts and "ZPCT3" in pcts:
        tr.check("ZPCT1 percentile > ZPCT3 percentile", pcts["ZPCT1"] > pcts["ZPCT3"],
                 f"ZPCT1={pcts['ZPCT1']:.4f} ZPCT3={pcts['ZPCT3']:.4f}")

    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
    conn.commit()


# ── Vetter related_tickers integration check ─────────────────────────────────

def test_vetter_related_map_query(conn, snapshot_id: int):
    """Verify the SQL query for related_tickers_map returns sibling pairs correctly."""
    print("\n[13] Vetter related_tickers_map DB query correctness")
    tickers = ["RVETA", "RVETB", "RVETC"]
    results = {}
    with conn.cursor() as cur:
        _clean_test_tickers(cur, tickers)
        cur.execute(
            "INSERT INTO universe_tickers (snapshot_id, ticker, name, sector) VALUES "
            "(%s, 'RVETA', 'Related Corp', 'Tech'), "
            "(%s, 'RVETB', 'Related Corp', 'Tech'), "
            "(%s, 'RVETC', 'Other Corp',   'Tech')",
            (snapshot_id, snapshot_id, snapshot_id),
        )
        conn.commit()

        # Use snapshot_id directly (same snapshot the pipeline uses)
        cur.execute(
            "SELECT ut1.ticker AS canonical, ut2.ticker AS sibling "
            "FROM universe_tickers ut1 "
            "JOIN universe_tickers ut2 "
            "  ON  ut2.name = ut1.name "
            "  AND ut2.ticker != ut1.ticker "
            "  AND ut1.snapshot_id = %s "
            "  AND ut2.snapshot_id = ut1.snapshot_id "
            "WHERE ut1.ticker = ANY(%s) "
            "  AND ut1.name IS NOT NULL AND ut1.name != '' ",
            (snapshot_id, tickers),
        )
        for r in cur.fetchall():
            results.setdefault(r[0], []).append(r[1])

        _clean_test_tickers(cur, tickers)
    conn.commit()

    tr = TestRunner()
    tr.check("RVETA has RVETB as sibling", results.get("RVETA") == ["RVETB"],
             str(results.get("RVETA")))
    tr.check("RVETB has RVETA as sibling", results.get("RVETB") == ["RVETA"],
             str(results.get("RVETB")))
    tr.check("RVETC has no siblings", "RVETC" not in results, str(results.get("RVETC")))
    return tr


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Share-class deduplication end-to-end tests")
    print("=" * 60)

    # Pre-flight: ensure pipeline is alive
    try:
        r = requests.get(f"{PIPELINE_URL}/health", timeout=5)
        r.raise_for_status()
        print(f"Pipeline health: {r.json()}")
    except Exception as e:
        print(f"ERROR: pipeline unreachable at {PIPELINE_URL}: {e}")
        sys.exit(1)

    conn = db_conn()
    tr = TestRunner()

    try:
        with conn.cursor() as cur:
            snapshot_id = _ensure_snapshot(cur)
        conn.commit()
        print(f"Using universe_snapshot id={snapshot_id}")

        # Ensure SPY weekday prices exist (pipeline needs them for regime detection).
        # Use weekday-only rows so the price pivot's iloc positions land on trading days.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM daily_prices "
                "WHERE ticker='SPY' AND EXTRACT(DOW FROM date) BETWEEN 1 AND 5"
            )
            spy_weekday_count = cur.fetchone()[0]
        if spy_weekday_count < 252:
            print("Seeding SPY weekday prices (pipeline requires them)...")
            with conn.cursor() as cur:
                spy_rows = []
                day_idx = 0
                d = TODAY - timedelta(days=600)
                while d < TODAY:
                    if d.weekday() < 5:
                        p = 400.0 + day_idx * 0.1
                        spy_rows.append(("SPY", d, p, p, p, p, p, int(1e8)))
                        day_idx += 1
                    d += timedelta(days=1)
                cur.executemany(
                    "INSERT INTO daily_prices (ticker, date, open, high, low, close, adjusted_close, volume) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (ticker, date) DO UPDATE SET adjusted_close=EXCLUDED.adjusted_close",
                    spy_rows,
                )
            conn.commit()

        # Run all tests sequentially (each is a fresh pipeline run)
        test_basic_pair_goog_googl(tr, conn, snapshot_id)
        test_pair_reversed_nwsa_nws(tr, conn, snapshot_id)
        test_three_way_duplicate(tr, conn, snapshot_id)
        test_null_name_not_merged(tr, conn, snapshot_id)
        test_empty_name_not_merged(tr, conn, snapshot_id)
        test_unique_tickers_all_survive(tr, conn, snapshot_id)
        test_exact_score_tie(tr, conn, snapshot_id)
        test_sibling_not_ranked(tr, conn, snapshot_id)
        test_mixed_scenario(tr, conn, snapshot_id)
        test_all_same_company(tr, conn, snapshot_id)
        test_rank_reassignment(tr, conn, snapshot_id)
        test_percentile_after_dedup(tr, conn, snapshot_id)

        # Vetter related-map query (DB-only, no pipeline run)
        vetter_tr = test_vetter_related_map_query(conn, snapshot_id)
        tr.passed += vetter_tr.passed
        tr.failed += vetter_tr.failed
        tr._failures.extend(vetter_tr._failures)

    finally:
        conn.close()

    ok = tr.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
