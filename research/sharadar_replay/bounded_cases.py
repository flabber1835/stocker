"""Independent operational acquisition expectations; no production imports."""
from __future__ import annotations

import copy
import datetime as dt
from collections import Counter

import exchange_calendars as xcals

from .model import Fault, Revision, Scenario
from .oracle import StateMismatch
from .scenarios import FIRST, SECOND, SEED, THIRD, step


def window_start(through: str) -> str:
    cal = xcals.get_calendar("XNYS", start="2025-01-01", end="2027-01-01")
    index = cal.sessions.get_loc(cal.date_to_session(through))
    return cal.sessions[index - 299].date().isoformat()


def require_bounded_acquisition(transcript, *, step, successful):
    rows = [r for r in transcript if r["step"] == step.name]
    if any(r["channel"] == "pages" and r.get("table") in {"SEP", "ACTIONS"} for r in rows):
        raise StateMismatch("bounded acquisition used paginated SEP/ACTIONS")
    exports = [r for r in rows if r["channel"] == "export" and r["table"] == "SEP"]
    start, end = window_start(str(step.through)), str(step.through)
    for row in exports:
        query = row["query"]
        if not start <= query["date.gte"] <= query["date.lte"] <= end:
            raise StateMismatch("bounded acquisition escaped the independent 300-session interval")
    if successful and (not exports or min(r["query"]["date.gte"] for r in exports) != start
                       or max(r["query"]["date.lte"] for r in exports) != end):
        raise StateMismatch("bounded acquisition did not cover the independent 300-session interval")
    downloads = [r for r in rows if r["channel"] == "download"
                 and r.get("table") in {"SEP", "ACTIONS", "TICKERS"}]
    counts = Counter((r["table"], r["query"].get("date.gte"), r["query"].get("date.lte"))
                     for r in downloads)
    if any(count != 1 for count in counts.values()):
        raise StateMismatch("bounded acquisition downloaded a table/partition more than once")
    if any(f.kind in {"creating_export", "stale_export"} for f in step.faults) and downloads:
        raise StateMismatch("unavailable export preflight downloaded source files")


def build_bounded_scenarios():
    start = window_start(SEED)

    def current(name, day, **kwargs):
        return step(name, day, date_from=start, **kwargs)

    seed = current("bootstrap", SEED, ready=False,
                   required_blockers=("SEP recent complete reconciliation",))
    cases = {}

    def add(name, steps, **kwargs):
        cases[name] = Scenario(name=name, acquisition_mode="bounded_operational",
            seed_start=dt.date.fromisoformat(start), seed=seed, steps=tuple(steps), **kwargs)

    add("bounded_happy_daily", [current("day_one", FIRST), current("day_two", SECOND),
                                current("day_three", THIRD)])
    add("bounded_correction_and_cash", [current("correct", FIRST, correction=104, dividend=1),
        current("revise", SECOND, correction=108, dividend=2),
        current("stable", THIRD, correction=108, dividend=2)])
    add("bounded_same_day", [current("first", FIRST),
        current("later", FIRST, hour=23, correction=106),
        current("next", SECOND, correction=106)])
    split_steps = []
    previous = seed.expected
    for name, day in (("split", FIRST), ("repeat", SECOND)):
        candidate = current(name, day, split=True)
        retained = {r[:2]: r for r in previous.bars if r[1] < window_start(day)}
        expected = candidate.expected.model_copy(update={"bars": tuple(
            retained.get(r[:2], r) for r in candidate.expected.bars)})
        split_steps.append(candidate.model_copy(update={"expected": expected}))
        previous = expected
    add("bounded_split_preserves_older_prices", split_steps)

    for table in ("ACTIONS", "TICKERS", "SEP"):
        fault = Fault(table=table, channel="export", kind="creating_export")
        add(f"bounded_{table.lower()}_creating", [current("unavailable", FIRST,
            faults=(fault,), expected=seed.expected, ready=False,
            error="export status=creating", required_blockers=("freshness",)),
            current("recover", SECOND)], recovery_from="recover")
    for kind in ("stale_export", "invalid_zip"):
        fault = Fault(table="SEP", channel="export", kind=kind)
        add(f"bounded_sep_{kind}", [current("damaged", FIRST, faults=(fault,),
            expected=seed.expected, ready=False, error="SharadarSnapshotExportError",
            required_blockers=("freshness",)), current("recover", SECOND)], recovery_from="recover")

    changed = copy.deepcopy(current("source_changes", FIRST).tables["SEP"])
    for row in changed:
        row["open"] += 1
    # The same first partition is probed before download and corroborated after.
    revision = Revision(name="new_sep_generation", table="SEP", channel="export",
                        query={"date.gte": window_start(FIRST)}, rows=changed)
    bad = current("source_changes", FIRST, expected=seed.expected, ready=False,
                  error="VendorPublicationUnstable", required_blockers=("freshness",))
    add("bounded_sep_refresh_changes", [bad.model_copy(update={"revisions": (revision,)}),
        current("recover", SECOND)], recovery_from="recover")
    return cases
