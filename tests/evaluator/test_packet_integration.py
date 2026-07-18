"""Ephemeral-Postgres integration suite for the evaluator PACKET — the weekly
review's evidence base. The audit proved bugs live in these SQL sections
(alphabetical-head counterfactuals, asymmetric SPY windows, partial_success
miscount); this suite runs the REAL queries against the REAL migrated schema so
a broken column, join, or aggregate fails in CI instead of silently feeding the
LLM false evidence.

Skips cleanly when Postgres binaries / alembic aren't available on the runner.
"""
import asyncio
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.integration.conftest import _EphemeralPostgres, _alembic_upgrade  # noqa: E402

TODAY = datetime.now(timezone.utc).date()
D = lambda days_ago: TODAY - timedelta(days=days_ago)  # noqa: E731


def _ts(d: date, hour: int = 12) -> datetime:
    return datetime.combine(d, time(hour), tzinfo=timezone.utc)


# Deterministic fixture ids referenced across seed + assertions
FACTOR_RUN = str(uuid.uuid4())
RANKING_RUN = str(uuid.uuid4())
VETTER_RUN = str(uuid.uuid4())
PORTFOLIO_RUN = str(uuid.uuid4())
DELTA_RUN = str(uuid.uuid4())

# 85 vetter exclusions: the first 80 ALPHABETICALLY ("A00".."A79") rallied +10%
# after the veto; the last 5 ("Z80".."Z84") fell -10%. The pre-fix code
# aggregated over the alphabetical head only → pct_fell 0.0; correct is 5/85.
GOOD_AFTER_VETO = [f"A{i:02d}" for i in range(80)]
BAD_AFTER_VETO = [f"Z{i:02d}" for i in range(80, 85)]
EXCLUDED = GOOD_AFTER_VETO + BAD_AFTER_VETO


async def _seed(engine) -> None:
    from sqlalchemy import text
    async with engine.begin() as conn:
        async def ex(sql, rows):
            await conn.execute(text(sql), rows)

        # ── prices: SPY daily for 30d WITH A GAP AT D-7 (weekend-style) ──────
        spy_rows = [{"t": "SPY", "d": D(i), "px": 400 + (30 - i)}
                    for i in range(31) if i != 7]
        await ex("INSERT INTO daily_prices (ticker, date, adjusted_close, close) "
                 "VALUES (:t, :d, :px, :px)", spy_rows)
        # excluded tickers: 100 on D-10 → 110 (A*) / 90 (Z*) today
        px_rows = []
        for t in EXCLUDED:
            end_px = 110 if t in GOOD_AFTER_VETO else 90
            px_rows += [{"t": t, "d": D(10), "px": 100},
                        {"t": t, "d": D(0), "px": end_px}]
        await ex("INSERT INTO daily_prices (ticker, date, adjusted_close, close) "
                 "VALUES (:t, :d, :px, :px)", px_rows)

        # ── chain lineage: factor → ranking → vetter/portfolio ───────────────
        await ex("INSERT INTO factor_runs (run_id, strategy_id, config_hash, score_date, "
                 " regime, status, started_at, completed_at) "
                 "VALUES (:id, 's1', 'h1', :d, 'bull_calm', 'success', :st, :st)",
                 [{"id": FACTOR_RUN, "d": D(1), "st": _ts(D(1))}])
        await ex("INSERT INTO factor_scores (run_id, ticker, score_date, momentum, quality) "
                 "VALUES (:rid, :t, :d, 0.5, 0.4)",
                 [{"rid": FACTOR_RUN, "t": t, "d": D(1)} for t in ("A00", "A01")])
        await ex("INSERT INTO ranking_runs (run_id, source_factor_run_id, strategy_id, "
                 " config_hash, regime, rank_date, status, started_at, completed_at) "
                 "VALUES (:id, :f, 's1', 'h1', 'bull_calm', :d, 'success', :st, :st)",
                 [{"id": RANKING_RUN, "f": FACTOR_RUN, "d": D(1), "st": _ts(D(1))}])
        await ex("INSERT INTO rankings (run_id, source_factor_run_id, strategy_id, regime, "
                 " rank_date, ticker, rank, composite_score) "
                 "VALUES (:r, :f, 's1', 'bull_calm', :d, :t, :rk, 0.9)",
                 [{"r": RANKING_RUN, "f": FACTOR_RUN, "d": D(1), "t": t, "rk": i + 1}
                  for i, t in enumerate(("A00", "A01"))])
        await ex("INSERT INTO vetter_runs (run_id, source_ranking_run_id, strategy_id, "
                 " model, status, started_at, completed_at) "
                 "VALUES (:id, :r, 's1', 'det', 'success', :st, :st)",
                 [{"id": VETTER_RUN, "r": RANKING_RUN, "st": _ts(D(1))}])
        await ex("INSERT INTO vetter_exclusions (run_id, ticker, reason, confidence, "
                 " risk_type, created_at) "
                 "VALUES (:rid, :t, 'test veto', 'medium', 'drawdown', :c)",
                 [{"rid": VETTER_RUN, "t": t, "c": _ts(D(10))} for t in EXCLUDED])
        await ex("INSERT INTO portfolio_runs (run_id, source_ranking_run_id, strategy_id, "
                 " config_hash, regime, portfolio_date, status, started_at, completed_at) "
                 "VALUES (:id, :r, 's1', 'h1', 'bull_calm', :d, 'success', :st, :st)",
                 [{"id": PORTFOLIO_RUN, "r": RANKING_RUN, "d": D(1), "st": _ts(D(1))}])
        await ex("INSERT INTO portfolio_holdings (run_id, source_ranking_run_id, strategy_id, "
                 " regime, portfolio_date, ticker, position, weight, original_rank) "
                 "VALUES (:p, :r, 's1', 'bull_calm', :d, 'A00', 1, 0.5, 1)",
                 [{"p": PORTFOLIO_RUN, "r": RANKING_RUN, "d": D(1)}])

        # ── exits: two names exited on D-5 (base price 100 @ D-10 → +10%) ────
        await ex("INSERT INTO delta_runs (run_id, strategy_id, status, run_date, "
                 " started_at, completed_at) "
                 "VALUES (:id, 's1', 'success', :d, :st, :st)",
                 [{"id": DELTA_RUN, "d": D(5), "st": _ts(D(5))}])
        await ex("INSERT INTO delta_intents (run_id, ticker, action, reason) "
                 "VALUES (:r, :t, 'exit', 'orphan timer')",
                 [{"r": DELTA_RUN, "t": t} for t in ("A00", "A01")])

        # ── account curve: D-21 100k → today 103k (sync gap in between) ──────
        await ex("INSERT INTO alpaca_sync_runs (run_id, status, account_value, "
                 " started_at, completed_at) "
                 "VALUES (:id, 'success', :v, :st, :st)",
                 [{"id": str(uuid.uuid4()), "v": 100000, "st": _ts(D(21))},
                  {"id": str(uuid.uuid4()), "v": 103000, "st": _ts(D(0))}])

        # ── ingest health: nightly partial_success is the NORMAL success ─────
        await ex("INSERT INTO ingest_runs (run_id, job_type, status, started_at, completed_at) "
                 "VALUES (:id, 'fetch-data', :s, :st, :st)",
                 [{"id": str(uuid.uuid4()), "s": s, "st": _ts(D(i + 1))}
                  for i, s in enumerate(["partial_success", "partial_success",
                                         "partial_success", "failed"])])

        # ── prior reviews: one week reviewed 3x (re-runs), one week once ─────
        wk_old = D(9).isocalendar()
        wk_new = D(2).isocalendar()
        rep_rows = []
        for i, ch in enumerate(("c1", "c2", "c3")):   # same week, later started wins
            rep_rows.append({"id": str(uuid.uuid4()), "d": D(9), "y": wk_old.year,
                             "w": wk_old.week, "ch": ch, "st": _ts(D(9), hour=6 + i)})
        rep_rows.append({"id": str(uuid.uuid4()), "d": D(2), "y": wk_new.year,
                         "w": wk_new.week, "ch": "c9", "st": _ts(D(2))})
        await ex("INSERT INTO evaluator_reports (run_id, status, as_of_date, iso_year, "
                 " iso_week, config_hash, report_markdown, started_at, completed_at) "
                 "VALUES (:id, 'success', :d, :y, :w, :ch, 'md', :st, :st)", rep_rows)

        # ── one applied config change (Phase 3 audit trail) ──────────────────
        await ex("INSERT INTO config_changes (id, config_path, config_field, old_value, "
                 " new_value, config_hash_before, config_hash_after) "
                 "VALUES (CAST(:id AS uuid), '/strategies/x.yaml', 'portfolio_builder.max_positions', "
                 " '30'::jsonb, '25'::jsonb, 'aaaa', 'bbbb')",
                 [{"id": str(uuid.uuid4())}])

        # ── universe snapshot ────────────────────────────────────────────────
        sid = (await conn.execute(text(
            "INSERT INTO universe_snapshots (etf_ticker, snapshot_date, ticker_count) "
            "VALUES ('AV', :d, 2) RETURNING id"), {"d": D(1)})).scalar()
        await ex("INSERT INTO universe_tickers (snapshot_id, ticker, sector) "
                 "VALUES (:s, :t, 'Tech')",
                 [{"s": sid, "t": t} for t in ("A00", "A01")])


@pytest.fixture(scope="module")
def db_engine(tmp_path_factory):
    try:
        pg = _EphemeralPostgres()
        pg.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        try:
            _alembic_upgrade(pg.sync_dsn)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"alembic upgrade unavailable: {exc}")
        from sqlalchemy.pool import NullPool
        from sqlalchemy.ext.asyncio import create_async_engine

        def make_engine():
            # NullPool: each asyncio.run() uses its own event loop; pooled
            # asyncpg connections are loop-bound and would break across tests.
            return create_async_engine(pg.async_dsn, poolclass=NullPool)

        asyncio.run(_run_with_engine(make_engine, _seed))
        yield make_engine
    finally:
        pg.stop()


async def _run_with_engine(make_engine, fn):
    engine = make_engine()
    try:
        return await fn(engine)
    finally:
        await engine.dispose()


def _call(make_engine, section_fn):
    """Run one packet section against a fresh engine/connection."""
    async def _inner(engine):
        async with engine.connect() as conn:
            return await section_fn(conn)
    return asyncio.run(_run_with_engine(make_engine, _inner))


# ── the broad guard: every section runs real SQL against the real schema ──────

def test_full_packet_builds_with_no_section_errors(db_engine, monkeypatch):
    monkeypatch.setenv("STRATEGY_CONFIG_PATH",
                       str(ROOT / "strategies" / "momentum_rotation_v2.yaml"))
    monkeypatch.setenv("ARTIFACTS_PATH", "/nonexistent")   # backtest_lab degrades
    from app.packet import build_packet
    packet = asyncio.run(_run_with_engine(db_engine, build_packet))
    expected = {
        "system_architecture", "strategy_config", "universe_snapshot", "gate_audit",
        "selection_audit", "factor_coverage", "risk_gate_stats",
        "factor_evidence_weekly", "prior_reviews", "account_performance",
        "closed_trades", "open_positions", "vetter_outcomes", "exit_outcomes",
        "current_target_book", "config_history", "applied_config_changes",
        "system_health", "hypothesis_ledger", "backtest_lab",
    }
    assert expected <= set(packet)
    broken = {k: v for k, v in packet.items()
              if isinstance(v, dict) and "error" in v}
    assert not broken, f"sections errored against the real schema: {broken}"


# ── regression locks for the audit's confirmed bugs ───────────────────────────

def test_system_health_counts_partial_success_as_ok(db_engine):
    from app.packet import _system_health
    out = _call(db_engine, _system_health)
    assert out["ingest_runs"] == {"failed_14d": 1, "success_14d": 3}


def test_vetter_outcomes_aggregate_over_all_not_alphabetical_head(db_engine):
    from app.packet import _vetter_outcomes
    out = _call(db_engine, _vetter_outcomes)
    assert out["excluded_count"] == 85                      # real total, not 80
    assert len(out["exclusions"]) == 80                     # display capped
    assert out["exclusions_truncated"] is True
    # Correct: 5 of 85 fell. Pre-fix (alphabetical head only): 0 of 80 → 0.0.
    assert out["pct_fell_after_veto"] == round(5 / 85, 3)
    expected_avg = (80 * 0.10 + 5 * (-0.10)) / 85
    assert out["avg_fwd_return_of_excluded"] == pytest.approx(expected_avg, abs=1e-3)


def test_exit_outcomes_realized_forward_return(db_engine):
    from app.packet import _exit_outcomes
    out = _call(db_engine, _exit_outcomes)
    assert out["exit_count"] == 2
    assert out["avg_fwd_return_after_exit"] == pytest.approx(0.10, abs=1e-3)


def test_account_vs_spy_windows_symmetric(db_engine):
    from app.packet import _account_performance
    out = _call(db_engine, _account_performance)
    h = out["returns"]["1w"]
    # account: last sync point <= cutoff(D-7) is D-21 → 103000/100000
    assert h["account_return"] == pytest.approx(0.03, abs=1e-4)
    # SPY anchored the SAME way: last close <= D-7 is D-8 (422; D-7 is a gap
    # day). Pre-fix used the first close AFTER the cutoff (D-6 = 424).
    assert h["spy_return"] == pytest.approx(430 / 422 - 1, abs=1e-4)
    assert h["excess"] == pytest.approx(0.03 - (430 / 422 - 1), abs=1e-3)


def test_prior_reviews_one_entry_per_iso_week_latest_wins(db_engine):
    from app.packet import _prior_reviews
    out = _call(db_engine, _prior_reviews)
    weeks = out["reports"]
    assert len(weeks) == 2 == out["distinct_weeks_covered"]
    assert out["total_distinct_review_weeks_ever"] == 2    # the streak hard bound
    tripled = next(w for w in weeks if w["same_week_rerun_count"] == 3)
    assert tripled["config_hash_at_review"] == "c3"        # latest-started re-run
    single = next(w for w in weeks if w["same_week_rerun_count"] == 1)
    assert single["config_hash_at_review"] == "c9"
