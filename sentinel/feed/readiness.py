"""Readiness authority facade with current-session and source-maintenance proof.

The historical readiness implementation remains byte-for-byte in
:mod:`sentinel.feed.readiness_impl`. This boundary keeps its rolling-window
checks and adds facts a healthy historical window cannot prove:

* the CURRENT frontier still carries every strategy-critical price domain;
* SEP `lastupdated` maintenance covered the decision frontier;
* ACTIONS negative space has current whole-export authority; and
* the exact Wealth Core decision-history window was completely reconciled
  against an export-backed SEP source after all daily mutations finished.
"""
from __future__ import annotations

import datetime as _dt

from sentinel.feed import authority as _authority
from sentinel.feed import anomalies as _anomalies
from sentinel.feed import calendar as _cal
from sentinel.feed import maintenance as _maintenance
from sentinel.feed import publication as _publication
from sentinel.feed import readiness_impl as _impl
from sentinel.feed import recent_reconciliation as _recent

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

MIN_FRONTIER_DOMAIN_COVERAGE = _authority.MIN_FRONTIER_DOMAIN_COVERAGE
RUNTIME_BLOCKING_SPLIT_KINDS = (
    "SPLIT_DISAGREEMENT",
    "SPLIT_ONLY_DERIVED",
    "SEAM_SPLIT_UNCORROBORATED",
    "AMBIGUOUS_SPLIT_MULTIPLICITY",
)


def _source_day(value) -> _dt.date:
    text = str(value)
    try:
        return _dt.date.fromisoformat(text[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"readiness observation has invalid date {value!r}") from exc


def _decision_day(value) -> _dt.date:
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"published decision frontier has invalid date {value!r}") from exc


def _add_recent_check(conn, result, *, source_day, frontier_day) -> None:
    name = "SEP recent complete reconciliation"
    try:
        recent = _recent.load_cursor(conn)
        current = _publication.require_current(conn)
    except Exception as exc:  # noqa: BLE001
        result.add(name, _impl.FAIL,
                   f"recent SEP reconciliation state cannot be validated: "
                   f"{type(exc).__name__}: {exc}")
        return
    if recent is None:
        result.add(
            name, _impl.FAIL,
            "no export-backed complete reconciliation covers the current Wealth "
            "Core decision-history window")
    elif recent.processed_through > source_day:
        result.add(
            name, _impl.FAIL,
            f"recent SEP proof {recent.processed_through} is ahead of readiness "
            f"observation date {source_day}")
    elif recent.processed_through < frontier_day:
        result.add(
            name, _impl.FAIL,
            f"recent complete SEP proof ends {recent.processed_through}, behind "
            f"decision frontier {frontier_day}; a deletion can bypass lastupdated")
    elif recent.publication_version != current.version:
        result.add(
            name, _impl.FAIL,
            f"recent SEP proof names corpus v{recent.publication_version} but "
            f"current publication is v{current.version}; a later mutation has "
            "not been re-proved against complete source",
            {"processed_through": recent.processed_through.isoformat(),
             "proof_publication_version": recent.publication_version,
             "current_publication_version": current.version})
    else:
        result.add(
            name, _impl.PASS,
            f"complete export-backed SEP history through {recent.processed_through} "
            f"matches current corpus v{current.version}",
            {"processed_through": recent.processed_through.isoformat(),
             "publication_version": recent.publication_version})


def _add_split_agreement_check(conn, result, *, frontier: str) -> None:
    """Refuse a normally-ready corpus with unresolved split economics.

    This is intentionally full-history.  A split changes the cumulative signal
    basis on every later session, so limiting the query to the warm-up window
    would let an older unresolved share-count event silently authorize a plan.
    The anomaly read is publication-aware: a later published resolution clears
    the event while an unpublished retry cannot.
    """
    name = "split source agreement"
    try:
        rows = _anomalies.active_rows(
            conn, start="1900-01-01", end=str(frontier),
            kinds=RUNTIME_BLOCKING_SPLIT_KINDS)
    except Exception as exc:  # noqa: BLE001
        result.add(
            name, _impl.FAIL,
            f"published split dispositions cannot be validated: "
            f"{type(exc).__name__}: {exc}")
        return

    if not rows:
        result.add(
            name, _impl.PASS,
            f"no active unsafe published split disposition exists through "
            f"{frontier}",
            0)
        return

    shown = "; ".join(
        f"{row['ticker']} {row['session']} (corpus v"
        f"{row['publication_version']})" for row in rows[:10])
    more = f" (+{len(rows) - 10} more)" if len(rows) > 10 else ""
    result.add(
        name, _impl.FAIL,
        f"{len(rows)} active unsafe published split disposition(s) through "
        f"{frontier}: {shown}{more}. Share-count evidence is uncorroborated, "
        "ambiguous, or contradictory; no normal plan may be prepared until a "
        "later published disposition resolves each event.",
        [{"kind": row["kind"], "ticker": row["ticker"],
          "session": row["session"],
          "publication_version": row["publication_version"]}
         for row in rows])


def _add_source_maintenance_checks(conn, result, *, today,
                                   required_through) -> None:
    """Bind READY to maintenance authority for the published decision frontier."""
    try:
        source_day = _source_day(today)
        frontier_day = _decision_day(required_through)
    except ValueError as exc:
        result.add("SEP mutation watermark", _impl.FAIL, str(exc))
        result.add("ACTIONS complete reconciliation", _impl.FAIL, str(exc))
        result.add("SEP recent complete reconciliation", _impl.FAIL, str(exc))
        return
    if frontier_day > source_day:
        detail = (
            f"published decision frontier {frontier_day} is ahead of readiness "
            f"observation date {source_day}")
        result.add("SEP mutation watermark", _impl.FAIL, detail)
        result.add("ACTIONS complete reconciliation", _impl.FAIL, detail)
        result.add("SEP recent complete reconciliation", _impl.FAIL, detail)
        return

    try:
        sep = _maintenance.load_sep_cursor(conn)
    except Exception as exc:  # noqa: BLE001
        result.add(
            "SEP mutation watermark", _impl.FAIL,
            f"SEP mutation cursor cannot be validated: {type(exc).__name__}: {exc}")
    else:
        if sep is None:
            result.add(
                "SEP mutation watermark", _impl.FAIL,
                "no complete seed/reconciliation has established the Sharadar "
                "SEP lastupdated watermark")
        elif sep.processed_through > source_day:
            result.add(
                "SEP mutation watermark", _impl.FAIL,
                f"SEP mutation cursor {sep.processed_through} is ahead of "
                f"readiness observation date {source_day}",
                {"processed_through": sep.processed_through.isoformat(),
                 "required_through": frontier_day.isoformat(),
                 "source_date": source_day.isoformat(),
                 "publication_version": sep.publication_version})
        elif sep.processed_through < frontier_day:
            result.add(
                "SEP mutation watermark", _impl.FAIL,
                f"SEP historical mutations are processed through "
                f"{sep.processed_through}, behind published decision frontier "
                f"{frontier_day}; a current price frontier alone is not enough",
                {"processed_through": sep.processed_through.isoformat(),
                 "required_through": frontier_day.isoformat(),
                 "source_date": source_day.isoformat(),
                 "publication_version": sep.publication_version})
        else:
            result.add(
                "SEP mutation watermark", _impl.PASS,
                f"historical SEP mutations reconciled through "
                f"{sep.processed_through}, covering decision frontier "
                f"{frontier_day}",
                {"processed_through": sep.processed_through.isoformat(),
                 "required_through": frontier_day.isoformat(),
                 "publication_version": sep.publication_version})

    try:
        actions = _maintenance.load_actions_cursor(conn)
    except Exception as exc:  # noqa: BLE001
        result.add(
            "ACTIONS complete reconciliation", _impl.FAIL,
            f"ACTIONS reconciliation cursor cannot be validated: "
            f"{type(exc).__name__}: {exc}")
    else:
        if actions is None:
            result.add(
                "ACTIONS complete reconciliation", _impl.FAIL,
                "no complete export-backed Sharadar ACTIONS reconciliation has "
                "been recorded")
        elif actions.processed_through > source_day:
            result.add(
                "ACTIONS complete reconciliation", _impl.FAIL,
                f"ACTIONS reconciliation cursor {actions.processed_through} "
                f"is ahead of readiness observation date {source_day}")
        else:
            age = max(0, (frontier_day - actions.processed_through).days)
            if age >= _maintenance.ACTIONS_RECONCILE_DAYS:
                result.add(
                    "ACTIONS complete reconciliation", _impl.FAIL,
                    f"complete ACTIONS authority was {age} day(s) old at "
                    f"decision frontier {frontier_day}; a full export "
                    f"reconciliation is due every "
                    f"{_maintenance.ACTIONS_RECONCILE_DAYS} day(s)",
                    {"processed_through": actions.processed_through.isoformat(),
                     "required_through": frontier_day.isoformat(),
                     "source_date": source_day.isoformat(), "age_days": age,
                     "publication_version": actions.publication_version})
            else:
                result.add(
                    "ACTIONS complete reconciliation", _impl.PASS,
                    f"complete ACTIONS authority was {age} day(s) old at "
                    f"decision frontier {frontier_day}, inside the "
                    f"{_maintenance.ACTIONS_RECONCILE_DAYS}-day cadence",
                    {"processed_through": actions.processed_through.isoformat(),
                     "required_through": frontier_day.isoformat(),
                     "age_days": age,
                     "publication_version": actions.publication_version})

    _add_recent_check(
        conn, result, source_day=source_day, frontier_day=frontier_day)


def check_readiness(conn, *, today=None, cfg=None):
    today = today or _dt.datetime.now(_dt.timezone.utc).isoformat()
    result = _impl.check_readiness(conn, today=today, cfg=cfg)
    frontier = _impl._q1(
        conn,
        "SELECT MAX(session) FROM sentinel_bars b"
        f" WHERE {_impl._VISIBLE_BARS}")
    if frontier is None:
        return result
    frontier = str(frontier)
    fresh = _cal.freshness(frontier, now_et=today)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COUNT(close_signal), COUNT(close_unadjusted),"
            " COUNT(open_unadjusted), COUNT(volume) FROM sentinel_bars b"
            " WHERE session >= %s AND session <= %s"
            f"   AND {_impl._VISIBLE_BARS}",
            (frontier, frontier))
        row = cur.fetchone()
    n = int(row[0] or 0)

    for present, label, protects in (
        (int(row[1] or 0), "signal domain",
         "momentum and the trailing-stop peak"),
        (int(row[2] or 0), "raw close",
         "marking and the 4% admission size"),
        (int(row[3] or 0), "raw open", "every fill"),
        (int(row[4] or 0), "volume", "ADV20 and signal dollar volume"),
    ):
        share = 0.0 if not n else present / n
        name = f"frontier {label}"
        value = {"session": frontier, "present": present, "rows": n,
                 "coverage": round(share, 4), "freshness": fresh.to_dict()}
        if share < MIN_FRONTIER_DOMAIN_COVERAGE:
            result.add(
                name, _impl.FAIL,
                f"{label} is present on {share:.1%} of bars on frontier "
                f"{frontier}; authority requires at least "
                f"{MIN_FRONTIER_DOMAIN_COVERAGE:.0%}. It backs {protects}, and "
                f"healthy history may not dilute a broken current session "
                f"into PASS.", value)
        else:
            result.add(
                name, _impl.PASS,
                f"{share:.1%} coverage on frontier {frontier}", value)

    _add_split_agreement_check(conn, result, frontier=frontier)
    _add_source_maintenance_checks(
        conn, result, today=today, required_through=frontier)
    return result
