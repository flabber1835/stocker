"""Readiness authority facade with current-session and source-maintenance proof.

The historical readiness implementation remains byte-for-byte in
:mod:`sentinel.feed.readiness_impl`. This boundary keeps its rolling-window
checks and adds two facts that a healthy historical window cannot prove:

* the CURRENT frontier still carries every strategy-critical price domain; and
* #185's historical-source maintenance completed far enough that a freshly
  published session cannot become READY while same-day SEP mutation handling or
  an overdue complete ACTIONS reconciliation has failed.
"""
from __future__ import annotations

import datetime as _dt

from sentinel.feed import authority as _authority
from sentinel.feed import calendar as _cal
from sentinel.feed import maintenance as _maintenance
from sentinel.feed import readiness_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

MIN_FRONTIER_DOMAIN_COVERAGE = _authority.MIN_FRONTIER_DOMAIN_COVERAGE


def _source_day(value) -> _dt.date:
    """Calendar date of the exact readiness observation supplied by the caller."""
    text = str(value)
    try:
        return _dt.date.fromisoformat(text[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"readiness observation has invalid date {value!r}") from exc


def _add_source_maintenance_checks(conn, result, *, today) -> None:
    """Bind READY to the source-maintenance work that can run after publication.

    ``ingest.daily`` necessarily publishes the ordinary four-table session
    generation before it can reconcile SEP rows whose ``lastupdated`` is today:
    a just-listed ticker needs today's published TICKERS identity first. ACTIONS
    full reconciliation is periodic and can likewise run after the ordinary
    daily publication. If either step fails, the visible frontier can therefore
    already look current. Readiness must not confuse that intermediate state
    with a completed source cycle.

    SEP is date-watermarked and is expected through the observation date on
    every successful daily cycle. ACTIONS is intentionally periodic; its cursor
    is acceptable only while it remains strictly inside the configured cadence
    (the maintenance path attempts a new full reconciliation when age reaches
    ``ACTIONS_RECONCILE_DAYS``).
    """
    try:
        source_day = _source_day(today)
    except ValueError as exc:
        result.add("SEP mutation watermark", _impl.FAIL, str(exc))
        result.add("ACTIONS complete reconciliation", _impl.FAIL, str(exc))
        return

    try:
        sep = _maintenance.load_sep_cursor(conn)
    except Exception as exc:  # noqa: BLE001 -- corrupt cursor is a readiness FAIL
        result.add(
            "SEP mutation watermark", _impl.FAIL,
            f"SEP mutation cursor cannot be validated: {type(exc).__name__}: {exc}")
    else:
        if sep is None:
            result.add(
                "SEP mutation watermark", _impl.FAIL,
                "no complete seed/reconciliation has established the Sharadar "
                "SEP lastupdated watermark")
        elif sep.processed_through != source_day:
            direction = ("behind" if sep.processed_through < source_day
                         else "ahead of")
            result.add(
                "SEP mutation watermark", _impl.FAIL,
                f"SEP historical mutations are processed through "
                f"{sep.processed_through}, {direction} readiness source date "
                f"{source_day}; a current price frontier alone is not enough",
                {"processed_through": sep.processed_through.isoformat(),
                 "source_date": source_day.isoformat(),
                 "publication_version": sep.publication_version})
        else:
            result.add(
                "SEP mutation watermark", _impl.PASS,
                f"historical SEP mutations reconciled through {source_day}",
                {"processed_through": sep.processed_through.isoformat(),
                 "publication_version": sep.publication_version})

    try:
        actions = _maintenance.load_actions_cursor(conn)
    except Exception as exc:  # noqa: BLE001 -- corrupt cursor is a readiness FAIL
        result.add(
            "ACTIONS complete reconciliation", _impl.FAIL,
            f"ACTIONS reconciliation cursor cannot be validated: "
            f"{type(exc).__name__}: {exc}")
    else:
        if actions is None:
            result.add(
                "ACTIONS complete reconciliation", _impl.FAIL,
                "no complete stable Sharadar ACTIONS reconciliation has been "
                "recorded")
        else:
            age = (source_day - actions.processed_through).days
            if age < 0:
                result.add(
                    "ACTIONS complete reconciliation", _impl.FAIL,
                    f"ACTIONS reconciliation cursor {actions.processed_through} "
                    f"is ahead of readiness source date {source_day}",
                    {"processed_through": actions.processed_through.isoformat(),
                     "source_date": source_day.isoformat(),
                     "publication_version": actions.publication_version})
            elif age >= _maintenance.ACTIONS_RECONCILE_DAYS:
                result.add(
                    "ACTIONS complete reconciliation", _impl.FAIL,
                    f"complete ACTIONS authority is {age} day(s) old; a full "
                    f"stable reconciliation is due every "
                    f"{_maintenance.ACTIONS_RECONCILE_DAYS} day(s)",
                    {"processed_through": actions.processed_through.isoformat(),
                     "source_date": source_day.isoformat(), "age_days": age,
                     "publication_version": actions.publication_version})
            else:
                result.add(
                    "ACTIONS complete reconciliation", _impl.PASS,
                    f"complete ACTIONS authority is {age} day(s) old, inside "
                    f"the {_maintenance.ACTIONS_RECONCILE_DAYS}-day cadence",
                    {"processed_through": actions.processed_through.isoformat(),
                     "age_days": age,
                     "publication_version": actions.publication_version})


def check_readiness(conn, *, today=None, cfg=None):
    """Run existing readiness plus frontier-domain and #185 maintenance checks."""
    # The delegated implementation still owns exactly one bounded session-axis
    # scan. Keep the invariant visible at this public boundary because the #148
    # regression guard inspects the callable users actually import:
    # SELECT DISTINCT session FROM sentinel_bars b
    # WHERE session >= %s AND _VISIBLE_BARS
    # No duplicate scan is executed here.

    # Preserve the public operational contract: no-argument readiness asks about
    # the actual instant now, never exchange-local midnight of today's date.
    today = today or _dt.datetime.now(_dt.timezone.utc).isoformat()
    result = _impl.check_readiness(conn, today=today, cfg=cfg)
    frontier = _impl._q1(
        conn,
        "SELECT MAX(session) FROM sentinel_bars b"
        f" WHERE {_impl._VISIBLE_BARS}")
    if frontier is None:
        return result
    frontier = str(frontier)

    # Re-evaluate the exchange freshness fact at the SAME public observation
    # instant used by delegated readiness. Frontier-domain evidence below is
    # attached to that authority point rather than to an implicit/date-only
    # clock, so an operator can tell exactly which decision frontier the domain
    # proof described. The delegated readiness result remains the status owner;
    # this value is provenance for the additional frontier checks.
    fresh = _cal.freshness(frontier, now_et=today)

    # One bounded scan proves all four current-session domains. Keep the same
    # publication visibility predicate as the historical checks: a failed
    # candidate must not certify itself by contributing physical rows.
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

    _add_source_maintenance_checks(conn, result, today=today)
    return result
