"""Hand-auditable fixture worlds and separately constructed expected corpora."""
from __future__ import annotations

import datetime as dt

import exchange_calendars as xcals

from .model import Corpus, Fault, Scenario, Step

START = "2025-12-01"
SEED = "2026-08-17"
FIRST = "2026-08-18"
SECOND = "2026-08-19"
THIRD = "2026-08-20"
SID = {"AAA": "SIM-AAA", "BBB": "SIM-BBB"}
OLD_CORRECTION = "2026-03-02"
SPLIT = "2026-08-03"  # exactly the first daily overlap's leading edge
DIVIDEND = "2026-06-01"  # well outside the daily price overlap


def sessions(through):
    calendar = xcals.get_calendar("XNYS", start="2025-01-01", end="2027-01-01")
    return tuple(s.date().isoformat() for s in calendar.sessions_in_range(START, through))


def world(through: str, *, correction: int | None = None,
          dividend: int | None = None, split: bool = False):
    axis = sessions(through)
    sep, sfp, tickers, actions = [], [], [], []
    expected_bars, expected_sfp, expected_defensive = [], [], []
    expected_identities, expected_actions = [], []
    for ticker, sid in SID.items():
        tickers.append({"table": "SEP", "ticker": ticker, "permaticker": sid,
            "category": "Domestic Common Stock", "sector": "Industrials", "exchange": "NYSE",
            "relatedtickers": "", "firstpricedate": START, "lastpricedate": through, "isdelisted": "N"})
        expected_identities.append((sid, ticker, "Domestic Common Stock", "Industrials", "",
                                    START, through, False))
        actions.append({"ticker": ticker, "date": START, "action": "listed", "name": ticker,
                        "value": None, "contraticker": None, "contraname": None})
        expected_actions.append((ticker, START, "listed", ticker, None, None, None))
        for day in axis:
            # Provider encoding from the fictional economic schedule.
            price = correction if ticker == "AAA" and day == OLD_CORRECTION and correction else 100
            factor = 2 if split and ticker == "AAA" and day < SPLIT else 1
            if split and ticker == "AAA" and day >= SPLIT:
                price = 50
            source_close = price / factor
            updated = through if ticker == "AAA" and day == OLD_CORRECTION and correction else day
            sep.append({"ticker": ticker, "date": day, "open": source_close, "close": source_close,
                        "closeunadj": price, "volume": 1_000_000 * factor, "lastupdated": updated})

            # The expected raw ledger values come directly from the economic schedule.
            expected_price = 100
            if correction and ticker == "AAA" and day == OLD_CORRECTION:
                expected_price = correction
            if split and ticker == "AAA" and day >= SPLIT:
                expected_price = 50
            signal = 50 if split and ticker == "AAA" else expected_price
            expected_bars.append((sid, day, ticker, signal, expected_price, expected_price,
                1_000_000, 2 if split and ticker == "AAA" and day == SPLIT else 1,
                dividend if dividend and ticker == "AAA" and day == DIVIDEND else 0))
    if split:
        actions.append({"ticker": "AAA", "date": SPLIT, "action": "split", "name": "AAA",
                        "value": 2, "contraticker": None, "contraname": None})
        expected_actions.append(("AAA", SPLIT, "split", "AAA", 2, None, None))
    if dividend:
        actions.append({"ticker": "AAA", "date": DIVIDEND, "action": "dividend", "name": "AAA",
                        "value": dividend, "contraticker": None, "contraname": None})
        expected_actions.append(("AAA", DIVIDEND, "dividend", "AAA", dividend, None, None))
    for day in axis:
        for ticker, price in (("SPY", 400), ("BIL", 100)):
            sfp.append({"ticker": ticker, "date": day, "open": price, "close": price,
                        "closeadj": price, "closeunadj": price})
        expected_sfp.append((day, 400))
        expected_defensive.append((day, "SENTINEL:BIL", "BIL", 100, 100, 100, 100))
    return ({"SEP": tuple(sep), "SFP": tuple(sfp), "TICKERS": tuple(tickers), "ACTIONS": tuple(actions)},
            Corpus(bars=tuple(expected_bars), actions=tuple(expected_actions),
                   identities=tuple(expected_identities), spy=tuple(expected_sfp),
                   defensive=tuple(expected_defensive)))


def step(name, day, *, hour=22, expected=None, ready=True, error=None,
         faults=(), publication_failure=False, required_blockers=(), **world_options):
    tables, corpus = world(day, **world_options)
    return Step(name=name, at=dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00"),
                through=dt.date.fromisoformat(day), tables=tables,
                expected=expected or corpus, ready=ready, error=error, faults=faults,
                required_blockers=required_blockers, publication_failure=publication_failure)


def build_scenarios() -> dict[str, Scenario]:
    seed = step("bootstrap", SEED, ready=False,
                required_blockers=("SEP recent complete reconciliation",))
    initial = seed.expected
    base = {"seed_start": dt.date.fromisoformat(START), "seed": seed}
    cases = {}

    def add(name, steps, **kw):
        cases[name] = Scenario(name=name, **(base | kw), steps=tuple(steps))

    add("happy_daily", [step("day_one", FIRST), step("day_two", SECOND), step("day_three", THIRD)])
    add("old_price_correction", [step("correct_old_price", FIRST, correction=104),
                                  step("continue_corrected", SECOND, correction=104)])
    add("same_day_revision", [step("first_observation", FIRST),
        step("later_same_date", FIRST, hour=23, correction=106),
        step("next_session", SECOND, correction=106)])
    add("late_dividend", [step("late_action_arrives", FIRST, dividend=1),
                           step("repeat_action", SECOND, dividend=1)])
    add("split_overlap_boundary", [step("replay_split_boundary", FIRST, split=True),
                                    step("repeat_split", SECOND, split=True)],
        seed=step("bootstrap", SEED, ready=False, split=True,
                  required_blockers=("SEP recent complete reconciliation",)))
    for name, fault, error in (
        ("malformed_tickers", Fault(table="TICKERS", kind="missing_column"), "SharadarProtocolError"),
        ("incomplete_tickers", Fault(table="TICKERS", kind="omit_ticker", ticker="BBB"), "SharadarSnapshotExportError"),
        ("stale_tickers_export", Fault(table="TICKERS", channel="export", kind="stale_export"), "SharadarSnapshotExportError"),
        ("interrupted_after_identity", Fault(table="ACTIONS", kind="http_400"), "SharadarRequestError"),
    ):
        add(name, [step("interrupted", FIRST, faults=(fault,), expected=initial,
                        ready=False, error=error, required_blockers=("freshness",)),
                   step("recover", SECOND), step("continue", THIRD)], recovery_from="recover")
    return cases
