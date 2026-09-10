"""Combined economics and deterministic within-attempt source revisions."""
from __future__ import annotations

import copy
import datetime as dt

from .model import Revision, Scenario
from .scenarios import DIVIDEND, FIRST, OLD_CORRECTION, SECOND, SPLIT, START, THIRD, sessions, step


def build_review_scenarios(seed):
    cases = {}

    def add(name, steps, **kwargs):
        cases[name] = Scenario(name=name, seed_start=dt.date.fromisoformat(START),
                               seed=seed, steps=tuple(steps), **kwargs)

    for factor in (0.25, 0.5, 2, 4, 10):
        for label, correction_date in (("old", OLD_CORRECTION),
                                       ("dividend", DIVIDEND), ("after_split", "2026-08-10")):
            options = dict(split=True, split_factor=factor, correction_date=correction_date,
                           dividend=1)
            add(f"combined_split_{str(factor).replace('.', '_')}_{label}",
                [step("combined_events", FIRST, correction=104, **options),
                 step("revised_price_and_cash", SECOND, correction=108,
                      **dict(options, dividend=2)),
                 step("stable", THIRD, correction=108, **dict(options, dividend=2))])

    initial = seed.expected
    reference_start = sessions(FIRST)[-41]
    hidden_references = initial.model_copy(update={
        "spy": tuple(r for r in initial.spy if r[0] < reference_start),
        "defensive": tuple(r for r in initial.defensive if r[0] < reference_start),
    })
    schedules = [
        ("sep_between_observations", "SEP", 2, 0, "open", 1),
        ("sep_during_pagination", "SEP", 1, 7, "open", 1),
        ("actions_during_corroboration", "ACTIONS", 2, 0, "value", 0.25),
        ("sfp_during_corroboration", "SFP", 2, 0, "closeadj", 1),
        ("tickers_between_observations", "TICKERS", 2, 0, "sector", "Technology"),
        ("tickers_during_corroboration", "TICKERS", 3, 0, "sector", "Technology"),
    ]
    for name, table, observation, offset, field, change in schedules:
        expected = initial if name == "tickers_between_observations" else hidden_references
        bad = step("source_changes", FIRST, expected=expected, ready=False,
                   error="VendorPublicationUnstable", required_blockers=("freshness",))
        tables = copy.deepcopy(bad.tables)
        if table == "ACTIONS":
            tables[table] = (*tables[table], dict(ticker="AAA", date=FIRST,
                action="dividend", name="AAA", value=0.25, contraticker=None, contraname=None))
        revised = copy.deepcopy(tables[table])
        for row in revised:
            if table == "ACTIONS" and row["date"] != FIRST:
                continue
            row[field] = change if isinstance(change, str) else row[field] + change
        query = {} if table == "TICKERS" else {"date.lte": FIRST}
        if table == "SEP":
            query["date.gte"] = SPLIT
        revision = Revision(name="new_vendor_vintage", table=table, observation=observation,
                            after_rows=offset, query=query, rows=revised)
        bad = bad.model_copy(update={"tables": tables, "revisions": (revision,)})
        add(name, [bad, step("recover", SECOND), step("stable", THIRD)],
            recovery_from="recover", page_size=7)
    return cases
