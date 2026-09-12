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
BASE_DIVIDEND = "2026-07-01"
AUTHORITY_SESSION = "2026-05-04"


def sessions(through):
    calendar = xcals.get_calendar("XNYS", start="2025-01-01", end="2027-01-01")
    return tuple(s.date().isoformat() for s in calendar.sessions_in_range(START, through))


def world(through: str, *, correction: int | None = None,
          dividend: int | None = None, split: bool = False,
          correction_date: str = OLD_CORRECTION,
          split_factor: float = 2, split_date: str = SPLIT):
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
        for index, day in enumerate(axis):
            # Provider encoding from the fictional economic schedule.
            price = 100
            factor = split_factor if split and ticker == "AAA" and day < split_date else 1
            if split and ticker == "AAA" and day >= split_date:
                price = 100 / split_factor
            if correction is not None and ticker == "AAA" and day == correction_date:
                price = correction
            raw_open = price + (index % 5 + 1) * (1 if ticker == "AAA" else -1)
            raw_volume = 1_000_000 + index * 100 + (0 if ticker == "AAA" else 50)
            source_close = price / factor
            updated = through if ticker == "AAA" and ((day == correction_date and correction) or split) else day
            sep.append({"ticker": ticker, "date": day, "open": raw_open / factor, "close": source_close,
                        "closeunadj": price, "volume": raw_volume * factor, "lastupdated": updated})

            # The expected raw ledger values come directly from the economic schedule.
            expected_price = 100
            if split and ticker == "AAA" and day >= split_date:
                expected_price = 100 / split_factor
            if correction is not None and ticker == "AAA" and day == correction_date:
                expected_price = correction
            signal = (expected_price / split_factor
                      if split and ticker == "AAA" and day < split_date else expected_price)
            expected_open = expected_price + (index % 5 + 1) * (1 if ticker == "AAA" else -1)
            expected_bars.append((sid, day, ticker, signal, expected_price, expected_open,
                1_000_000 + index * 100 + (0 if ticker == "AAA" else 50),
                split_factor if split and ticker == "AAA" and day == split_date else 1,
                (dividend if dividend and ticker == "AAA" and day == DIVIDEND else
                 0.5 if ticker == "BBB" and day == BASE_DIVIDEND else 0)))
    # Production checks for recent global ACTIONS activity. An ordinary BBB
    # cash dividend gives the small world that required positive source evidence.
    actions.append({"ticker": "BBB", "date": BASE_DIVIDEND, "action": "dividend", "name": "BBB",
                    "value": 0.5, "contraticker": None, "contraname": None})
    expected_actions.append(("BBB", BASE_DIVIDEND, "dividend", "BBB", 0.5, None, None))
    if split:
        actions.append({"ticker": "AAA", "date": split_date, "action": "split", "name": "AAA",
                        "value": split_factor, "contraticker": None, "contraname": None})
        expected_actions.append(("AAA", split_date, "split", "AAA", split_factor, None, None))
    if dividend:
        source_dividend = (dividend / split_factor
                           if split and DIVIDEND < split_date else dividend)
        actions.append({"ticker": "AAA", "date": DIVIDEND, "action": "dividend", "name": "AAA",
                        "value": source_dividend, "contraticker": None, "contraname": None})
        expected_actions.append(("AAA", DIVIDEND, "dividend", "AAA",
                                 dividend / split_factor if split and DIVIDEND < split_date else dividend,
                                 None, None))
    # Historical replay must supply the reviewed TRI source event to the real
    # cash authority. A delisted one-session security keeps that proof separate
    # from the AAA/BBB fault schedules. Declare source and economic cash values
    # independently so the oracle detects an unapplied adjudication.
    if AUTHORITY_SESSION in axis:
        tickers.append({"table": "SEP", "ticker": "TRI", "permaticker": "SIM-TRI-AUTHORITY",
            "category": "Domestic Common Stock", "sector": "Industrials", "exchange": "NYSE",
            "relatedtickers": "", "firstpricedate": AUTHORITY_SESSION,
            "lastpricedate": AUTHORITY_SESSION, "isdelisted": "Y"})
        expected_identities.append(("SIM-TRI-AUTHORITY", "TRI", "Domestic Common Stock",
            "Industrials", "", AUTHORITY_SESSION, AUTHORITY_SESSION, True))
        actions.append({"ticker": "TRI", "date": AUTHORITY_SESSION, "action": "dividend",
            "name": "TRI", "value": 1.36, "contraticker": None, "contraname": None})
        expected_actions.append(("TRI", AUTHORITY_SESSION, "dividend", "TRI", 1.36, None, None))
        sep.append({"ticker": "TRI", "date": AUTHORITY_SESSION, "open": 99.5, "close": 100.0,
            "closeunadj": 100.0, "volume": 1_000_000, "lastupdated": AUTHORITY_SESSION})
        expected_bars.append(("SIM-TRI-AUTHORITY", AUTHORITY_SESSION, "TRI",
            100.0, 100.0, 99.5, 1_000_000, 1, 1.435518))
    for index, day in enumerate(axis):
        for ticker, base in (("SPY", 400), ("BIL", 100)):
            close = base + index / 4
            sfp.append({"ticker": ticker, "date": day, "open": close - 0.5, "close": close,
                        "closeadj": close * 1.25, "closeunadj": close * 2})
        expected_sfp.append((day, 500 + index * 0.3125))
        expected_defensive.append((day, "SENTINEL:BIL", "BIL",
            99.5 + index / 4, 100 + index / 4,
            125 + index * 0.3125, 200 + index / 2))
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
    add("revised_dividend", [step("initial_dividend", FIRST, dividend=1),
                             step("correct_dividend", SECOND, dividend=2),
                             step("repeat_correction", THIRD, dividend=2)])
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
    reference_start = sessions(FIRST)[-41]
    hidden_references = initial.model_copy(update={
        "spy": tuple(r for r in initial.spy if r[0] < reference_start),
        "defensive": tuple(r for r in initial.defensive if r[0] < reference_start),
    })
    add("incomplete_sep", [step("partial_prices", FIRST, ready=False,
        error="SepListingPopulationIncomplete", expected=hidden_references,
        faults=(Fault(table="SEP", kind="omit_ticker", ticker="BBB"),),
        required_blockers=("freshness",)), step("recover", SECOND), step("continue", THIRD)],
        recovery_from="recover")
    # Identical previously published SEP values retain their original owner;
    # the newly inserted session remains invisible until publication succeeds.
    hidden_overlap = hidden_references
    add("publication_interruption", [step("publication_interrupted", FIRST,
        publication_failure=True, ready=False, error="scheduled publication interruption",
        expected=hidden_overlap, required_blockers=("freshness",)),
        step("recover_publication", SECOND), step("continue", THIRD)], recovery_from="recover_publication")
    from .adversarial import build_adversarial_scenarios
    cases.update(build_adversarial_scenarios(seed))
    from .review_cases import build_review_scenarios
    cases.update(build_review_scenarios(seed))
    return cases
