"""Readiness authority facade with current-session domain proof.

The historical readiness implementation remains byte-for-byte in
:mod:`sentinel.feed.readiness_impl`.  This boundary keeps its rolling-window
checks and adds a separate frontier verdict so 126 healthy sessions cannot hide
a collapsed current decision domain.
"""
from __future__ import annotations

from sentinel.feed import authority as _authority
from sentinel.feed import readiness_impl as _impl

for _name in dir(_impl):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_impl, _name)

MIN_FRONTIER_DOMAIN_COVERAGE = _authority.MIN_FRONTIER_DOMAIN_COVERAGE


def check_readiness(conn, *, today=None, cfg=None):
    """Run the existing contract plus explicit frontier-session domain checks."""
    result = _impl.check_readiness(conn, today=today, cfg=cfg)
    frontier = _impl._q1(
        conn,
        "SELECT MAX(session) FROM sentinel_bars b"
        f" WHERE {_impl._VISIBLE_BARS}")
    if frontier is None:
        return result
    frontier = str(frontier)

    for column, label, protects in (
        ("close_signal", "signal domain", "momentum and the trailing-stop peak"),
        ("close_unadjusted", "raw close", "marking and the 4% admission size"),
        ("open_unadjusted", "raw open", "every fill"),
        ("volume", "volume", "ADV20 and signal dollar volume"),
    ):
        n, present = _impl._domain_coverage(conn, column, frontier, frontier)
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
