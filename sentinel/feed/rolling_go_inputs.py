"""Rolling GO data preparation and read-only evidence; no runtime authority."""
from __future__ import annotations

from contextlib import contextmanager
from statistics import median

from sentinel import rolling_checkpoint, schema
from sentinel.core.rolling_inputs import cold_start_inputs, readiness_inputs, summarize_readiness
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
    instant = now or snapshots._now()
    return _validate(conn, pub, target=snapshots.source_final_session(instant))


def validate_status(conn, pub, *, now=None):
    """Same readiness contract, with counts instead of retained strategy bars."""
    instant = now or snapshots._now()
    binding, _summary, report = _assess(conn, pub,
        target=snapshots.source_final_session(instant), summary_only=True)
    if not report.ready:
        raise RollingGoRefused("ROLLING_INPUTS_NOT_READY: " + ", ".join(c.name for c in report.failures))
    return binding, report


def validate_reconstruction(conn, pub, *, summary_only=False):
    """Historical data readiness under actual authenticated availability evidence."""
    from sentinel import rolling_reconstruction_evidence
    rolling_reconstruction_evidence.require_dated(conn, pub)
    return _validate(conn, pub, target=pub.window_end, summary_only=summary_only)


def _validate(conn, pub, *, target, summary_only=False):
    binding, material, report = _assess(conn, pub, target=target, summary_only=summary_only)
    if not report.ready:
        raise RollingGoRefused("ROLLING_INPUTS_NOT_READY: " + ", ".join(c.name for c in report.failures))
    return binding, material, report


def assessment(conn, pub, *, now=None):
    """Report failed clauses without converting integrity failures to readiness."""
    instant = now or snapshots._now()
    return _assess(conn, pub, target=snapshots.source_final_session(instant), summary_only=True)[2]


def _assess(conn, pub, *, target, summary_only=False):
    binding = snapshots._bound(conn, pub)
    _, strategy = production_strategy()
    request = rolling_jobs.status(conn, binding["job_id"])["request"]
    if request["strategy_sha256"] != digest(strategy):
        raise RollingGoRefused("ROLLING_ACQUISITION_STRATEGY_CHANGED")
    if publication.chain_gaps(conn):
        raise RollingGoRefused("ROLLING_PUBLICATION_CHAIN_GAP")
    reader = readiness_inputs if summary_only else cold_start_inputs
    material = reader(conn, candidate_id=binding["candidate_id"], snapshot_id=binding["snapshot_id"])
    summary = material if summary_only else summarize_readiness(material)
    report = Readiness()
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
    frontier = summary.counts.get(summary.session, 0)
    prior_counts = [summary.counts[day] for day in summary.warmup_sessions[-20:]]
    baseline = median(prior_counts)
    report.add("rolling frontier population", PASS if frontier and frontier >= baseline * MIN_FRONTIER_POPULATION_RATIO else FAIL,
               "current cross-section compared with the preceding 20 sessions",
               {"frontier": frontier, "recent_median": baseline})
    for name in ("signal_close", "raw_close", "raw_open", "volume"):
        share = summary.frontier_positive[name] / frontier if frontier else 0
        report.add("rolling frontier " + name, PASS if share >= MIN_FRONTIER_DOMAIN_COVERAGE else FAIL,
                   "positive canonical domain coverage", share)
    for name in ("signal_close", "raw_close", "raw_open", "volume"):
        total = sum(summary.counts[day] for day in summary.warmup_sessions)
        share = summary.warmup_positive[name] / total if total else 0
        report.add("rolling warmup " + name, PASS if share >= .9 else FAIL,
                   "positive canonical domain coverage over the complete warmup", share)
    report.add("rolling issuer references", PASS if summary.related_issuers else FAIL,
               "current reference bundle includes related-ticker issuer evidence")
    return binding, material, report


def readiness(conn, *, now=None):
    """Call inside the caller's read-only transaction; never save a verdict."""
    with pinned(conn) as pub:
        _, report = validate_status(conn, pub, now=now)
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
            from sentinel.feed import rolling_store
            _, strategy = production_strategy()
            binding = snapshots._bound(conn, pub)
            actual = rolling_store.manifest(conn, binding['candidate_id']).window
            expected = snapshots.acquisition_window(conn, digest(strategy))
            # A pre-existing 300-session snapshot cannot silently satisfy fresh
            # Owned55 formation. Once an origin exists its original larger
            # generation remains usable until the next daily publication.
            from sentinel.feed.rolling_contract import FormationWindow
            if isinstance(expected, FormationWindow) and actual != expected:
                pub = None
        if is_rolling(pub) and pub.window_end == target_session:
            with snapshots.pinned(conn, commit=False) as (held, _):
                binding, _ = validate_status(conn, held)
            conn.commit()
            return {"schema": SCHEMA, "status": "ALREADY_CURRENT", **binding}
        _, strategy = production_strategy()
        job = snapshots.enqueue(conn, strategy_sha256=digest(strategy),
                                dependencies_sha256=digest({"scope": SCHEMA}),
                                budget_seconds=budget_seconds)
        conn.commit()
        binding = snapshots.prepare(conn, job)
        with snapshots.pinned(conn, commit=False) as (held, _):
            checked, _ = validate_status(conn, held)
            if checked != binding or held.window_end != target_session:
                raise RollingGoRefused("ROLLING_PREPARATION_PUBLICATION_CHANGED")
        conn.commit()
        return {"schema": SCHEMA, "status": "PUBLISHED", **binding}
    except BaseException:
        conn.rollback()
        raise
