"""Predeclared fault matrix and deterministic economic/transport variations."""
from __future__ import annotations

import datetime as dt
import random

from .model import Fault, Scenario
from .scenarios import FIRST, SECOND, THIRD, START, sessions, step


def build_adversarial_scenarios(seed):
    cases = {}
    initial = seed.expected
    reference_start = sessions(FIRST)[-41]
    hidden_references = initial.model_copy(update={
        'spy': tuple(r for r in initial.spy if r[0] < reference_start),
        'defensive': tuple(r for r in initial.defensive if r[0] < reference_start),
    })

    def add(name, steps, **kwargs):
        cases[name] = Scenario(name=name, seed_start=dt.date.fromisoformat(START),
                               seed=seed, steps=tuple(steps), **kwargs)

    def interrupted(name, day, fault, error):
        return step(name, day, faults=(fault,),
                    expected=hidden_references if fault.table == 'SEP' else initial,
                    ready=False, error=error, required_blockers=('freshness',))

    # An entire fault family is selected before its production execution.
    protocols = {
        'missing_column': 'SharadarProtocolError',
        'row_width': 'SharadarProtocolError',
        'missing_cursor': 'SharadarProtocolError',
        'invalid_json': 'SharadarProtocolError',
        'http_400': 'SharadarRequestError',
        'repeat_cursor': 'PaginationError',
    }
    for table in ('TICKERS', 'ACTIONS', 'SFP', 'SEP'):
        for kind, error in protocols.items():
            fault = Fault(table=table, kind=kind)
            name = f'{table.lower()}_{kind}_recovery'
            add(name, [interrupted('damaged', FIRST, fault, error),
                       step('recover', SECOND), step('repeat', SECOND, hour=23)],
                recovery_from='recover', page_size=1 if kind == 'repeat_cursor' else 53)
        for kind in ('row_width', 'http_400'):
            fault = Fault(table=table, kind=kind, after_rows=1)
            add(f'{table.lower()}_{kind}_after_prefix',
                [interrupted('valid_prefix_then_failure', FIRST, fault, protocols[kind]),
                 step('recover', SECOND)], recovery_from='recover', page_size=1)

    for table in ('SEP', 'SFP'):
        for kind in ('duplicate_row', 'conflicting_row'):
            fault = Fault(table=table, kind=kind)
            add(f'{table.lower()}_{kind}_recovery',
                [interrupted('duplicate_key', FIRST, fault, 'CanonicalSourceDuplicate'),
                 step('recover', SECOND), step('stable', THIRD)], recovery_from='recover')

    for kind in ('invalid_zip', 'missing_column', 'stale_export'):
        fault = Fault(table='TICKERS', channel='export', kind=kind)
        add(f'export_{kind}_recovery',
            [interrupted('bad_archive', FIRST, fault, 'SharadarSnapshotExportError'),
             step('recover', SECOND)], recovery_from='recover')

    for table in ('TICKERS', 'ACTIONS', 'SFP', 'SEP'):
        fault = Fault(table=table, kind='http_400')
        add(f'{table.lower()}_repeated_outage',
            [interrupted('outage_one', FIRST, fault, 'SharadarRequestError'),
             interrupted('outage_two', SECOND, fault, 'SharadarRequestError'),
             step('recover', THIRD), step('repeat', THIRD, hour=23)], recovery_from='recover')
    fault = Fault(table='TICKERS', kind='omit_ticker', ticker='BBB')
    add('persistent_incomplete_identity',
        [interrupted(f'blocked_{i}', day, fault, 'SharadarSnapshotExportError')
         for i, day in enumerate((FIRST, SECOND, THIRD))])

    # New correction values are source observations of older economic dates.
    # These are generated from the scenario seed, before production is invoked.
    axis = sessions('2026-07-01')[10:]
    for variation_seed in range(1, 17):
        rng = random.Random(variation_seed)
        day = rng.choice(axis)
        first_value = rng.randrange(80, 121)
        revised_value = first_value + rng.choice((-7, -3, 4, 9))
        options = dict(correction_date=day)
        add(f'seeded_revision_{variation_seed:03d}',
            [step('first_correction', FIRST, correction=first_value, **options),
             step('same_day_revision', FIRST, hour=23, correction=revised_value, **options),
             step('repeat_next_day', SECOND, correction=revised_value, **options),
             step('same_day_idempotence', SECOND, hour=23, correction=revised_value, **options)],
            variation_seed=variation_seed, page_size=rng.choice((7, 19, 53, 127)))
    add('late_split_restatement',
        [step('split_and_restatement', FIRST, split=True),
         step('same_day_repeat', FIRST, hour=23, split=True),
         step('next_day', SECOND, split=True)])
    return cases
