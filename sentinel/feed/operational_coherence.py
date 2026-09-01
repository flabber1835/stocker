"""Production dependency closure for unpublished corpus candidates.

Full retained-history coherence remains owned by ``publication.coherence``.
This module answers the narrower production question without changing the one
publication visibility rule: can any live unpublished row affect the current
state, its catch-up, its decision, or execution?
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from sentinel.controller.concordance import WITNESS_HISTORY_SESSIONS
from sentinel.core.session import (
    FEED_RESTART_SESSIONS,
    SessionState,
    _path_dependent_security_ids,
)
from sentinel.feed import calendar
from sentinel.feed import _publication_impl as _full
from sentinel.feed.requirements import PREFERRED_SESSIONS, REQUIRED_SPY_SESSIONS
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES

# This is deliberately expressed in source-owned session requirements.  The
# preferred window is the explicit operational safety margin above Wealth
# Core's 127-close minimum; the extra predecessor establishes the split/action
# seam immediately before it.
OPERATIONAL_HISTORY_SESSIONS = max(
    PREFERRED_SESSIONS,
    REQUIRED_CLOSES,
    FEED_RESTART_SESSIONS,
    REQUIRED_SPY_SESSIONS,
    WITNESS_HISTORY_SESSIONS,
)
ACTION_BOUNDARY_PREDECESSORS = 1
CLASSIFIER_VERSION = 1


@dataclass(frozen=True)
class OperationalBoundary:
    start: str
    end: str
    frontier: str
    cursor: str | None
    history_sessions: int = OPERATIONAL_HISTORY_SESSIONS
    predecessor_sessions: int = ACTION_BOUNDARY_PREDECESSORS

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "frontier": self.frontier,
            "cursor": self.cursor,
            "history_sessions": self.history_sessions,
            "predecessor_sessions": self.predecessor_sessions,
        }


@dataclass(frozen=True)
class CandidateClassification:
    run_id: str
    affected_start: str
    affected_end: str
    affected_security_count: int
    affected_securities: tuple[str, ...]
    evidence_kinds: tuple[str, ...]
    row_counts: Mapping[str, int]
    production_blocking: bool
    reasons: tuple[str, ...]

    @property
    def classification(self) -> str:
        return "PRODUCTION_BLOCKING" if self.production_blocking else "HISTORICAL_ONLY"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "affected_date_range": [self.affected_start, self.affected_end],
            "affected_security_count": self.affected_security_count,
            "affected_securities": list(self.affected_securities),
            "evidence_kinds": list(self.evidence_kinds),
            "row_counts": dict(sorted(self.row_counts.items())),
            "production_blocking": self.production_blocking,
            "classification": self.classification,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class OperationalCoherenceReport:
    version: int | None
    boundary: OperationalBoundary
    candidates: tuple[CandidateClassification, ...]

    @property
    def coherent(self) -> bool:
        return not any(item.production_blocking for item in self.candidates)

    @property
    def blocking(self) -> tuple[CandidateClassification, ...]:
        return tuple(item for item in self.candidates if item.production_blocking)

    @property
    def historical_only(self) -> tuple[CandidateClassification, ...]:
        return tuple(item for item in self.candidates if not item.production_blocking)

    def to_dict(self) -> dict:
        return {
            "coherent": self.coherent,
            "scope": "PRODUCTION_OPERATIONAL",
            "version": self.version,
            "boundary": self.boundary.to_dict(),
            "blocking_runs": [item.run_id for item in self.blocking],
            "historical_only_runs": [item.run_id for item in self.historical_only],
            "candidates": [item.to_dict() for item in self.candidates],
        }


def _relation_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"public.{name}",))
        return cur.fetchone()[0] is not None


def _frontier(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(session) FROM sentinel_bars b WHERE "
            + _full.visible_predicate("b"))
        row = cur.fetchone()
    if not row or row[0] is None:
        raise _full.CorpusIncoherent(
            "production operational coherence has no published bar frontier")
    return str(row[0])


def _cursor(conn) -> str | None:
    if not _relation_exists(conn, "sentinel_processed_sessions"):
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session FROM sentinel_processed_sessions "
            "WHERE cursor_name='catchup'")
        row = cur.fetchone()
    return None if not row else str(row[0])


def operational_boundary(conn, *, frontier: str | None = None) -> OperationalBoundary:
    end = str(frontier or _frontier(conn))
    required = OPERATIONAL_HISTORY_SESSIONS + ACTION_BOUNDARY_PREDECESSORS
    sessions = calendar.previous_sessions(end, required)
    if len(sessions) != required or sessions[-1] != end:
        raise _full.CorpusIncoherent(
            f"cannot establish {required}-session operational boundary through {end}")
    start = sessions[0]
    cursor = _cursor(conn)
    if cursor is not None and cursor < start:
        seam = calendar.previous_sessions(cursor, ACTION_BOUNDARY_PREDECESSORS + 1)
        if len(seam) != ACTION_BOUNDARY_PREDECESSORS + 1 or seam[-1] != cursor:
            raise _full.CorpusIncoherent(
                f"cannot establish catch-up predecessor before cursor {cursor}")
        start = seam[0]
    return OperationalBoundary(start=start, end=end, frontier=end, cursor=cursor)


def _json(value) -> object:
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value or "{}")


def _state_dependencies(conn) -> tuple[set[str], set[str]]:
    security_ids: set[str] = set()
    tickers: set[str] = set()
    if not _relation_exists(conn, "sentinel_processed_sessions"):
        return security_ids, tickers
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions "
            "WHERE cursor_name='catchup'")
        row = cur.fetchone()
    if not row or row[0] is None:
        return security_ids, tickers
    raw = _json(row[0])
    if not isinstance(raw, Mapping):
        raise _full.CorpusIncoherent("production catch-up state is not a JSON object")
    try:
        state = SessionState.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise _full.CorpusIncoherent(
            f"production catch-up state cannot establish dependencies: {exc}") from exc
    security_ids.update(_path_dependent_security_ids(state.wealth_core, state.pending))
    for sid, series in (state.feed.get("series") or {}).items():
        security_ids.add(str(sid))
        if isinstance(series, Mapping) and series.get("ticker"):
            tickers.add(str(series["ticker"]).upper())
    return security_ids, tickers


def _execution_dependencies(conn) -> tuple[set[str], set[str]]:
    security_ids: set[str] = set()
    tickers: set[str] = set()
    if _relation_exists(conn, "sentinel_execution_plans"):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT target_basket FROM sentinel_execution_plans "
                "WHERE superseded_by IS NULL ORDER BY created_at DESC LIMIT 1")
            row = cur.fetchone()
        if row and row[0] is not None:
            basket = _json(row[0])
            if not isinstance(basket, Mapping):
                raise _full.CorpusIncoherent("current execution basket is not an object")
            security_ids.update(str(sid) for sid in basket)
    if _relation_exists(conn, "sentinel_commands"):
        with conn.cursor() as cur:
            # Every durable command can contribute to expected-book
            # reconstruction, including a terminal filled command.
            cur.execute("SELECT DISTINCT security_id,UPPER(symbol) FROM sentinel_commands")
            for sid, ticker in cur.fetchall():
                security_ids.add(str(sid))
                if ticker:
                    tickers.add(str(ticker))
    return security_ids, tickers


def _window_dependencies(
        conn, *, boundary: OperationalBoundary) -> tuple[set[str], set[str]]:
    """Published securities that can contribute to operational transitions."""
    security_ids: set[str] = set()
    tickers: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT security_id,UPPER(ticker) FROM sentinel_bars b "
            "WHERE session BETWEEN %s AND %s AND "
            + _full.visible_predicate("b"),
            (boundary.start, boundary.end))
        for sid, ticker in cur.fetchall():
            security_ids.add(str(sid))
            if ticker:
                tickers.add(str(ticker))
    return security_ids, tickers


def production_dependencies(conn, *, boundary: OperationalBoundary,
                            extra_security_ids: Sequence[str] = ()
                            ) -> tuple[set[str], set[str]]:
    security_ids = {str(value) for value in extra_security_ids if str(value)}
    tickers: set[str] = set()
    window_ids, window_tickers = _window_dependencies(
        conn, boundary=boundary)
    state_ids, state_tickers = _state_dependencies(conn)
    execution_ids, execution_tickers = _execution_dependencies(conn)
    security_ids.update(window_ids)
    security_ids.update(state_ids)
    security_ids.update(execution_ids)
    tickers.update(window_tickers)
    tickers.update(state_tickers)
    tickers.update(execution_tickers)
    # ``feed_universe_current`` contains one row per historical identity
    # pairing. It supplies aliases for already-operational permanent identities;
    # mere retention in that table cannot promote a dead listing into current
    # production causality.
    if security_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT permaticker,UPPER(ticker),related_tickers "
                "FROM feed_universe_current WHERE permaticker=ANY(%s::text[])",
                (sorted(security_ids),))
            for sid, ticker, related in cur.fetchall():
                security_ids.add(str(sid))
                if ticker:
                    tickers.add(str(ticker))
                if related:
                    tickers.update(
                        item.strip().upper()
                        for item in re.split(r"[\s,]+", str(related))
                        if item.strip())
    return security_ids, tickers


def _candidate_sql() -> str:
    # ``propagates`` is true only for facts whose effect can cross the temporal
    # boundary. Ordinary old prices do not; share/action/terminal/identity
    # evidence does. Candidate rows are selected with the same lifecycle rules
    # as full historical coherence.
    return """
      WITH unpublished_runs AS (
        SELECT b.last_written_run_id AS run_id FROM sentinel_bars b
         WHERE b.last_written_run_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM sentinel_corpus_publications p
            WHERE p.run_id=b.last_written_run_id)
        UNION
        SELECT a.last_written_run_id FROM sentinel_actions a
         WHERE a.last_written_run_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM sentinel_corpus_publications p
            WHERE p.run_id=a.last_written_run_id)
        UNION
        SELECT r.last_written_run_id FROM sentinel_spy_total_return r
         WHERE r.last_written_run_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM sentinel_corpus_publications p
            WHERE p.run_id=r.last_written_run_id)
        UNION
        SELECT d.last_written_run_id FROM sentinel_defensive_bars d
         WHERE d.last_written_run_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM sentinel_corpus_publications p
            WHERE p.run_id=d.last_written_run_id)
        UNION
        SELECT v.last_written_run_id FROM sentinel_universe v
         WHERE v.last_written_run_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM sentinel_corpus_publications p
            WHERE p.run_id=v.last_written_run_id)
        UNION
        SELECT rr.last_written_run_id FROM sentinel_bar_split_repairs rr
         WHERE rr.last_written_run_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM sentinel_corpus_publications p
            WHERE p.run_id=rr.last_written_run_id)
        UNION
        SELECT o.last_written_run_id FROM sentinel_action_observations o
         WHERE NOT EXISTS (SELECT 1 FROM sentinel_corpus_publications p
                            WHERE p.run_id=o.last_written_run_id)
        UNION
        SELECT a.last_written_run_id FROM sentinel_corpus_anomalies a
         WHERE a.last_written_run_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM sentinel_corpus_publications p
            WHERE p.run_id=a.last_written_run_id)
      ), candidates AS (
        SELECT b.last_written_run_id AS run_id,
               CASE WHEN b.split_ratio<>1.0 THEN 'BAR_SPLIT'
                    WHEN b.dividend_per_share<>0.0 THEN 'BAR_DIVIDEND'
                    ELSE 'BAR_PRICE' END AS evidence_kind,
               b.session, b.security_id, UPPER(b.ticker) AS ticker,
               (b.split_ratio<>1.0 OR b.dividend_per_share<>0.0) AS propagates
          FROM sentinel_bars b JOIN unpublished_runs u
            ON u.run_id=b.last_written_run_id
        UNION ALL
        SELECT a.last_written_run_id,'LEGACY_ACTION',a.session,NULL,UPPER(a.ticker),TRUE
          FROM sentinel_actions a JOIN unpublished_runs u
            ON u.run_id=a.last_written_run_id
        UNION ALL
        SELECT r.last_written_run_id,'SPY_SENSOR',r.session,NULL,'SPY',FALSE
          FROM sentinel_spy_total_return r JOIN unpublished_runs u
            ON u.run_id=r.last_written_run_id
        UNION ALL
        SELECT d.last_written_run_id,'DEFENSIVE_PRICE',d.session,d.security_id,
               UPPER(d.ticker),FALSE
          FROM sentinel_defensive_bars d JOIN unpublished_runs u
            ON u.run_id=d.last_written_run_id
        UNION ALL
        SELECT v.last_written_run_id,'UNIVERSE_IDENTITY',v.snapshot_date,
               v.permaticker,UPPER(v.ticker),TRUE
          FROM sentinel_universe v JOIN unpublished_runs u
            ON u.run_id=v.last_written_run_id
        UNION ALL
        SELECT rr.last_written_run_id,'SPLIT_REPAIR',rr.session,rr.security_id,
               NULL,TRUE
          FROM sentinel_bar_split_repairs rr JOIN unpublished_runs u
            ON u.run_id=rr.last_written_run_id
          LEFT JOIN feed_ingest_runs r ON r.run_id=rr.last_written_run_id
         WHERE (r.run_id IS NULL OR r.status<>'failed')
           AND NOT EXISTS (
             SELECT 1 FROM sentinel_bar_split_repairs newer
             JOIN sentinel_corpus_publications p
               ON p.run_id=newer.last_written_run_id
             WHERE newer.security_id=rr.security_id
               AND newer.session=rr.session AND p.published_at>rr.repaired_at)
        UNION ALL
        SELECT o.last_written_run_id,'ACTION_'||UPPER(o.action),o.session,NULL,
               UPPER(o.ticker),TRUE
          FROM sentinel_action_observations o JOIN unpublished_runs u
            ON u.run_id=o.last_written_run_id
          LEFT JOIN LATERAL (
            SELECT e.state FROM sentinel_action_generation_events e
             WHERE e.generation_run_id=o.last_written_run_id
             ORDER BY e.event_id DESC LIMIT 1) latest ON TRUE
         WHERE COALESCE(latest.state,'PENDING')='PENDING'
        UNION ALL
        SELECT a.last_written_run_id,'ANOMALY_'||UPPER(a.kind),a.session,NULL,
               UPPER(a.ticker),TRUE
          FROM sentinel_corpus_anomalies a JOIN unpublished_runs u
            ON u.run_id=a.last_written_run_id
          LEFT JOIN LATERAL (
            SELECT e.state FROM sentinel_anomaly_observation_events e
             WHERE e.observation_id=a.observation_id
             ORDER BY e.event_id DESC LIMIT 1) latest ON TRUE
         WHERE COALESCE(latest.state,'PENDING')='PENDING'
      )
    """


def _classify(conn, *, boundary: OperationalBoundary,
              security_ids: set[str], tickers: set[str]) -> tuple[CandidateClassification, ...]:
    sql = _candidate_sql() + """
      SELECT run_id,evidence_kind,MIN(session),MAX(session),COUNT(*),
             BOOL_OR(session >= %s),
             BOOL_OR(propagates AND
               ((security_id IS NOT NULL AND security_id=ANY(%s::text[]))
                OR (security_id IS NULL AND ticker=ANY(%s::text[]))))
        FROM candidates
       GROUP BY run_id,evidence_kind
       ORDER BY run_id,evidence_kind
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            boundary.start, sorted(security_ids), sorted(tickers)))
        rows = cur.fetchall()
        cur.execute(_candidate_sql() + """
          , unique_identities AS (
            SELECT DISTINCT run_id,COALESCE(security_id,ticker) AS identity
              FROM candidates WHERE COALESCE(security_id,ticker) IS NOT NULL
          ), ranked AS (
            SELECT run_id,identity,ROW_NUMBER() OVER (
              PARTITION BY run_id ORDER BY identity) AS sample_rank
              FROM unique_identities
          )
          SELECT run_id,COUNT(*),
                 ARRAY_AGG(identity ORDER BY identity)
                   FILTER (WHERE sample_rank<=50)
            FROM ranked GROUP BY run_id ORDER BY run_id
        """)
        identity_summaries = {
            str(run_id): (int(count), tuple(str(value) for value in sample))
            for run_id, count, sample in cur.fetchall()}
    grouped: dict[str, dict] = {}
    for run_id, kind, start, end, count, temporal, propagated in rows:
        item = grouped.setdefault(str(run_id), {
            "start": str(start), "end": str(end),
            "kinds": [], "counts": {},
            "temporal": False, "propagated": False,
        })
        item["start"] = min(item["start"], str(start))
        item["end"] = max(item["end"], str(end))
        item["kinds"].append(str(kind))
        item["counts"][str(kind)] = int(count)
        item["temporal"] = item["temporal"] or bool(temporal)
        item["propagated"] = item["propagated"] or bool(propagated)

    output = []
    for run_id, raw in sorted(grouped.items()):
        identity_count, identity_sample = identity_summaries.get(
            run_id, (0, ()))
        reasons = []
        if raw["temporal"]:
            reasons.append(
                f"candidate evidence intersects operational session window "
                f"{boundary.start}..{boundary.end}")
        if raw["propagated"]:
            reasons.append(
                "older economic/identity evidence names an operational-window, "
                "path-dependent state, plan, command, or reconciliation identity")
        blocking = bool(reasons)
        if not blocking:
            reasons.append(
                "all candidate evidence is before the operational boundary and "
                "no economic propagation reaches current state or execution")
        output.append(CandidateClassification(
            run_id=run_id,
            affected_start=raw["start"], affected_end=raw["end"],
            affected_security_count=identity_count,
            affected_securities=identity_sample,
            evidence_kinds=tuple(sorted(raw["kinds"])),
            row_counts=raw["counts"], production_blocking=blocking,
            reasons=tuple(reasons)))
    return tuple(output)


def _assessment_hash(report: OperationalCoherenceReport,
                     candidate: CandidateClassification) -> str:
    payload = {
        "classifier_version": CLASSIFIER_VERSION,
        "version": report.version,
        "boundary": report.boundary.to_dict(),
        "candidate": candidate.to_dict(),
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def persist_report(conn, report: OperationalCoherenceReport) -> None:
    with conn.cursor() as cur:
        for candidate in report.candidates:
            cur.execute(
                "INSERT INTO sentinel_corpus_quarantine (assessment_sha256,run_id,"
                " publication_version,boundary_start,boundary_end,affected_start,"
                " affected_end,production_blocking,affected_securities,"
                " evidence_kinds,reasons,row_counts)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (assessment_sha256) DO NOTHING",
                (_assessment_hash(report, candidate), candidate.run_id,
                 report.version, report.boundary.start, report.boundary.end,
                 candidate.affected_start, candidate.affected_end,
                 candidate.production_blocking,
                 json.dumps({"count": candidate.affected_security_count,
                             "sample": list(candidate.affected_securities)}),
                 json.dumps(list(candidate.evidence_kinds)),
                 json.dumps(list(candidate.reasons)),
                 json.dumps(dict(candidate.row_counts))))


def operational_coherence(conn, *, frontier: str | None = None,
                          extra_security_ids: Sequence[str] = (),
                          persist: bool = False) -> OperationalCoherenceReport:
    publication = _full.current(conn)
    boundary = operational_boundary(conn, frontier=frontier)
    security_ids, tickers = production_dependencies(
        conn, boundary=boundary, extra_security_ids=extra_security_ids)
    report = OperationalCoherenceReport(
        version=publication.version if publication else None,
        boundary=boundary,
        candidates=_classify(
            conn, boundary=boundary, security_ids=security_ids, tickers=tickers))
    if persist:
        persist_report(conn, report)
    return report


def assert_operationally_coherent(
        conn, *, frontier: str | None = None,
        extra_security_ids: Sequence[str] = (), persist: bool = False
        ) -> OperationalCoherenceReport:
    report = operational_coherence(
        conn, frontier=frontier, extra_security_ids=extra_security_ids,
        persist=persist)
    if not report.coherent:
        details = "; ".join(
            f"{item.run_id} {item.affected_start}..{item.affected_end}: "
            + ", ".join(item.reasons) for item in report.blocking)
        raise _full.CorpusIncoherent(
            f"production operational coherence failed for "
            f"{len(report.blocking)} unpublished run(s): {details}. "
            "Candidate rows remain invisible; reconcile and publish a covering "
            "retry rather than exposing unresolved evidence.")
    return report


def quarantine_status(conn, *, limit: int = 20, persist: bool = False) -> dict:
    """Fresh live classification plus the state needed to render it safely.

    Durable assessments remain append-only evidence. The returned rows are
    always built from this call's dependency closure, so an older stored verdict
    can never masquerade as the live result.
    """
    if _full.current(conn) is None:
        return {
            "state": "AWAITING_FIRST_PUBLICATION",
            "reason": (
                "no published corpus frontier exists; production planning is "
                "unavailable while the first seed is in progress"),
            "boundary": None,
            "assessments": [],
        }
    try:
        report = operational_coherence(conn)
    except _full.CorpusIncoherent as exc:
        return {
            "state": "UNAVAILABLE",
            "reason": str(exc),
            "boundary": None,
            "assessments": [],
        }
    if persist and _relation_exists(conn, "sentinel_corpus_quarantine"):
        persist_report(conn, report)
    assessments = []
    for candidate in report.candidates[:max(0, int(limit))]:
        assessments.append({
            "run_id": candidate.run_id,
            "publication_version": report.version,
            "boundary_start": report.boundary.start,
            "boundary_end": report.boundary.end,
            "affected_start": candidate.affected_start,
            "affected_end": candidate.affected_end,
            "production_blocking": candidate.production_blocking,
            "affected_securities": {
                "count": candidate.affected_security_count,
                "sample": list(candidate.affected_securities),
            },
            "evidence_kinds": list(candidate.evidence_kinds),
            "reasons": list(candidate.reasons),
            "row_counts": dict(candidate.row_counts),
        })
    return {
        "state": "LIVE",
        "reason": None,
        "boundary": report.boundary.to_dict(),
        "assessments": assessments,
    }


__all__ = [
    "ACTION_BOUNDARY_PREDECESSORS", "CLASSIFIER_VERSION",
    "CandidateClassification", "OPERATIONAL_HISTORY_SESSIONS",
    "OperationalBoundary", "OperationalCoherenceReport",
    "assert_operationally_coherent", "operational_boundary",
    "operational_coherence", "persist_report", "production_dependencies",
    "quarantine_status",
]
