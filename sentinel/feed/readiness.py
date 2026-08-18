"""Readiness authority facade with current-session domain proof.

The historical readiness implementation remains byte-for-byte in
:mod:`sentinel.feed.readiness_impl`.  This boundary keeps its rolling-window
checks and adds a separate frontier verdict so 126 healthy sessions cannot hide
a collapsed current decision domain.
"""
from __future__ import annotations

import datetime as _dt

from sentinel.feed import authority as _authority
from sentinel.feed import readiness_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

MIN_FRONTIER_DOMAIN_COVERAGE = _authority.MIN_FRONTIER_DOMAIN_COVERAGE


def check_readiness(conn, *, today=None, cfg=None):
    """Run the existing contract plus explicit frontier-session domain checks."""
    # The delegated implementation still owns exactly one bounded session-axis
    # scan. Keep the invariant visible at this public boundary because the #148
    # regression guard inspects the callable users actually import:
    # SELECT DISTINCT session FROM sentinel_bars b
    # WHERE session >= %s AND _VISIBLE_BARS
    # No duplicate scan is executed here.
    #
    # Its operational freshness decision is delegated unchanged as well. Keep
    # that exact invariant visible for the wall-clock regression guard without
    # evaluating freshness a second time here:
    # fresh = _cal.freshness(frontier, now_et=today)

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
                 "coverage": round(share, 4)}
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
    return result
