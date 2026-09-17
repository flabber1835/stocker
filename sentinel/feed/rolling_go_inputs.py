"""Rolling GO data preparation and read-only evidence; no runtime authority."""
from __future__ import annotations

from contextlib import contextmanager
from statistics import median

from sentinel import rolling_checkpoint, schema
from sentinel.core.rolling_inputs import cold_start_inputs
from sentinel.feed import calendar, operational_snapshot as snapshots, publication
from sentinel.feed import rolling_jobs, runtime_schema
from sentinel.feed.rolling_contract import digest
from sentinel.feed.readiness_impl import Readiness, PASS, FAIL, MIN_FRONTIER_POPULATION_RATIO
from sentinel.feed.authority import MIN_FRONTIER_DOMAIN_COVERAGE
from sentinel.strategy import production_strategy

SCHEMA = "sentinel.rolling-go-inputs/1"
SCOPE = "ROLLING_CURRENT_INPUTS_ONLY"


class RollingGoRefused(RuntimeError):
    pass


def current(conn):
    """Explicit version-dispatched inspection; legacy readers stay unchanged."""
    return snapshots._current(conn)


def is_rolling(pub):
    return pub is not None and "rolling_snapshot" in pub.evidence


@contextmanager
def pinned(conn):
    with publication._core.pinned(conn, commit=False) as pub:
        publication._validate_publication(conn, pub, allow_snapshot=True)
        yield pub


def require_first_deployment(conn):
    # Never reinterpret failed-attempt rows as a new book or remove evidence.
    rolling_checkpoint.require_fresh(conn)


def require_schemas(conn):
    """Run before opening a pin/transaction: catalog validators end transactions."""
    schema.require_runtime_schema(conn)
    runtime_schema.require_feed_schema(conn)


def validate(conn, pub, *, now=None):
    """Verify selected content under the caller's schema-checked publication pin."""
    binding = snapshots._bound(conn, pub)
    _, strategy = production_strategy()
    request = rolling_jobs.status(conn, binding["job_id"])["request"]
    if request["strategy_sha256"] != digest(strategy):
        raise RollingGoRefused("ROLLING_ACQUISITION_STRATEGY_CHANGED")
    if publication.chain_gaps(conn):
        raise RollingGoRefused("ROLLING_PUBLICATION_CHAIN_GAP")
    material = cold_start_inputs(conn, candidate_id=binding["candidate_id"],
                                 snapshot_id=binding["snapshot_id"])
    report = Readiness()
    instant = now or snapshots._now()
    target = snapshots.source_final_session(instant)
    report.add("rolling source-final frontier", PASS if material.session == target else FAIL,
               f"snapshot {material.session}; source-final frontier {target}")
    report.add("rolling immutable input closure", PASS,
               "receipt, sealed content, independent coverage, calendar, references and actions verified")
    defensive_complete = all(
        getattr(row, name) is not None and getattr(row, name) > 0
        for row in material.benchmarks[-2:]
        for name in ("bil_open_signal", "bil_close_signal", "bil_close_adjusted", "bil_close_unadjusted"))
    report.add("rolling current BIL domains", PASS if defensive_complete else FAIL,
               "current and preceding defensive price domains")
    bars = list(material.bars)
    prior_counts = [len(material.warmup.bars_by_session[day]) for day in material.warmup.sessions[-20:]]
    baseline = median(prior_counts)
    report.add("rolling frontier population", PASS if bars and len(bars) >= baseline * MIN_FRONTIER_POPULATION_RATIO else FAIL,
               "current cross-section compared with the preceding 20 sessions",
               {"frontier": len(bars), "recent_median": baseline})
    for name in ("signal_close", "raw_close", "raw_open", "volume"):
        covered = sum(getattr(bar, name) is not None and getattr(bar, name) > 0 for bar in bars)
        share = covered / len(bars) if bars else 0
        report.add("rolling frontier " + name, PASS if share >= MIN_FRONTIER_DOMAIN_COVERAGE else FAIL,
                   "positive canonical domain coverage", share)
    for name in ("signal_close", "raw_close", "raw_open", "volume"):
        total = present = 0
        for day in material.warmup.sessions:
            for bar in material.warmup.bars_by_session[day]:
                total += 1
                present += getattr(bar, name) is not None and getattr(bar, name) > 0
        share = present / total if total else 0
        report.add("rolling warmup " + name, PASS if share >= .9 else FAIL,
                   "positive canonical domain coverage over the complete warmup", share)
    related = any(meta.related_tickers for meta in material.meta.values())
    report.add("rolling issuer references", PASS if related else FAIL,
               "current reference bundle includes related-ticker issuer evidence")
    if not report.ready:
        raise RollingGoRefused("ROLLING_INPUTS_NOT_READY: " + ", ".join(c.name for c in report.failures))
    return binding, material, report


def readiness(conn, *, now=None):
    """Call inside the caller's read-only transaction; never save a verdict."""
    with pinned(conn) as pub:
        _, _, report = validate(conn, pub, now=now)
        return report


def prepare(conn, *, target_session, budget_seconds=3600):
    """First-deployment coordinator; retry reuses the durable exact request."""
    try:
        require_schemas(conn)
        require_first_deployment(conn)
        return _prepare(conn, target_session=target_session, budget_seconds=budget_seconds)
    except BaseException:
        conn.rollback()
        raise


def _prepare(conn, *, target_session, budget_seconds=3600):
    """Shared acquisition; callers first prove fresh or attested runtime state."""
    try:
        if target_session != snapshots.source_final_session():
            raise RollingGoRefused("ROLLING_SOURCE_FINAL_TARGET_CHANGED")
        pub = current(conn)
        if is_rolling(pub) and pub.window_end == target_session:
            with snapshots.pinned(conn, commit=False) as (held, _):
                binding, _, _ = validate(conn, held)
            conn.commit()
            return {"schema": SCHEMA, "status": "ALREADY_CURRENT", **binding}
        _, strategy = production_strategy()
        job = snapshots.enqueue(conn, strategy_sha256=digest(strategy),
                                dependencies_sha256=digest({"scope": SCHEMA}),
                                budget_seconds=budget_seconds)
        conn.commit()
        binding = snapshots.prepare(conn, job)
        with snapshots.pinned(conn, commit=False) as (held, _):
            checked, _, _ = validate(conn, held)
            if checked != binding or held.window_end != target_session:
                raise RollingGoRefused("ROLLING_PREPARATION_PUBLICATION_CHANGED")
        conn.commit()
        return {"schema": SCHEMA, "status": "PUBLISHED", **binding}
    except BaseException:
        conn.rollback()
        raise
