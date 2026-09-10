"""Predeclared fault matrix and deterministic economic/transport variations."""
from __future__ import annotations

import datetime as dt
import copy
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
        damaged = step(name, day, faults=(fault,),
                    expected=hidden_references if fault.table == 'SEP' else initial,
                    ready=False, error=error, required_blockers=('freshness',))
        if fault.table == 'ACTIONS' and (fault.after_rows or fault.kind in {'row_width', 'repeat_cursor'}):
            # A valid prefix needs actual rows inside this daily request window.
            tables = copy.deepcopy(damaged.tables)
            tables['ACTIONS'] = (*tables['ACTIONS'], *(dict(ticker=t, date=day,
                action='dividend', name=t, value=0.25, contraticker=None, contraname=None)
                for t in ('AAA', 'BBB')))
            damaged = damaged.model_copy(update={'tables': tables})
        return damaged

    # An entire fault family is selected before its production execution.
    protocols = {
        'missing_column': 'SharadarProtocolError',
        'row_width': 'SharadarProtocolError',
        'missing_cursor': 'SharadarProtocolError',
        'invalid_json': 'SharadarProtocolError',
        'http_400': 'SharadarRequestError',
        'repeat_cursor': 'PaginationError',
        'rate_limit': 'SharadarRetryDeferred',
        'service_unavailable': 'SharadarRetryDeferred',
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
    for label, value in [('null', None), ('zero', 0), ('negative', -1),
                         ('nan', 'NaN'), ('infinite', 'Infinity'), ('text', 'broken')]:
        fault = Fault(table='SEP', kind='set_value', field='closeunadj', value=value)
        add(f'raw_close_{label}',
            [interrupted('invalid_raw_prices', FIRST, fault, 'FrontierDomainIncomplete'),
             step('recover', SECOND)], recovery_from='recover')

    for label, field, value in [
        ('empty_ticker', 'ticker', ''), ('missing_id', 'permaticker', None),
        ('invalid_listing_date', 'firstpricedate', '2025-02-30'),
        ('reversed_listing', 'firstpricedate', '2026-08-19'),
        ('invalid_delisted', 'isdelisted', 'perhaps'),
        ('overlapping_identity', 'ticker', 'AAA'),
    ]:
        bad = step('ambiguous_identity', FIRST, expected=initial, ready=False,
                   error='TickersStructureInvalid', required_blockers=('freshness',))
        tables = copy.deepcopy(bad.tables)
        tables['TICKERS'][1][field] = value
        bad = bad.model_copy(update={'tables': tables})
        add(f'identity_{label}', [bad, step('recover', SECOND)], recovery_from='recover')

    for label, value in [('nan', 'NaN'), ('infinite', 'Infinity'), ('text', 'broken')]:
        bad = step('corrupted_cash_action', FIRST, expected=initial, ready=False,
                   error='ACTIONS value is not a finite number', required_blockers=('freshness',))
        tables = copy.deepcopy(bad.tables)
        tables['ACTIONS'] = (*tables['ACTIONS'], dict(ticker='AAA', date=FIRST,
            action='dividend', name='AAA', value=value, contraticker=None, contraname=None))
        bad = bad.model_copy(update={'tables': tables})
        add(f'action_value_{label}', [bad, step('recover', SECOND)], recovery_from='recover')

    for label, values in [('unsubstantiated', (2,)), ('conflicting', (2, 3)),
                          ('zero', (0,)), ('negative', (-2,))]:
        bad = step('unresolved_split', FIRST, ready=False,
                   required_blockers=('split source agreement',))
        tables = copy.deepcopy(bad.tables)
        rows = tuple(dict(ticker='AAA', date=FIRST, action='split', name='AAA',
                          value=v, contraticker=None, contraname=None) for v in values)
        tables['ACTIONS'] = (*tables['ACTIONS'], *rows)
        expected = bad.expected.model_copy(update={'actions': (*bad.expected.actions,
            *((r['ticker'], r['date'], r['action'], r['name'], r['value'], None, None)
              for r in rows))})
        bad = bad.model_copy(update={'tables': tables, 'expected': expected})
        add(f'split_{label}_then_withdrawn', [bad, step('recover', SECOND), step('stable', THIRD)],
            recovery_from='recover')

    from .scenarios import SPLIT
    for label in ('wrong_ratio', 'missing_action'):
        bad = step('inconsistent_split', FIRST, split=True, ready=False,
                   required_blockers=('split source agreement',))
        tables = copy.deepcopy(bad.tables)
        if label == 'wrong_ratio':
            for row in tables['ACTIONS']:
                if row['action'] == 'split':
                    row['value'] = 3
            expected_actions = tuple((*r[:4], 3, *r[5:]) if r[2] == 'split' else r
                                     for r in bad.expected.actions)
            expected_bars = tuple((*r[:7], 1, r[8]) if r[0] == 'SIM-AAA' and r[1] == SPLIT else r
                                  for r in bad.expected.bars)
        else:
            tables['ACTIONS'] = tuple(r for r in tables['ACTIONS'] if r['action'] != 'split')
            expected_actions = tuple(r for r in bad.expected.actions if r[2] != 'split')
            expected_bars = bad.expected.bars
        bad = bad.model_copy(update={'tables': tables, 'expected': bad.expected.model_copy(
            update={'bars': expected_bars, 'actions': expected_actions})})
        add(f'split_{label}_then_corrected', [bad, step('recover', SECOND, split=True),
             step('stable', THIRD, split=True)], recovery_from='recover')
    for factor in (0.25, 0.5, 2, 4, 10):
        for effective in ('2026-08-03', '2026-08-18'):
            label = str(factor).replace('.', '_') + '_' + effective.replace('-', '')
            options = dict(split=True, split_factor=factor, split_date=effective)
            add(f'split_ratio_{label}',
                [step('authoritative_split', FIRST, **options),
                 step('same_day_repeat', FIRST, hour=23, **options),
                 step('continued', SECOND, **options)])
    for field, value, error in [
        ('lastupdated', '2099-01-01', 'SepUpdateEnvelopeViolation'),
        ('lastupdated', None, 'SepUpdateEnvelopeViolation'),
        ('date', 'invalid-date', 'SourceAuthorityRefused'),
        ('ticker', '', 'SourceAuthorityRefused'),
    ]:
        name = f'sep_invalid_{field}_{"missing" if value is None else "value"}'
        fault = Fault(table='SEP', kind='set_value', field=field, value=value)
        bad = interrupted('corrupted_key_or_clock', FIRST, fault, error)
        if field == 'lastupdated' and value is None:
            bad = bad.model_copy(update={'expected': step('expected', FIRST).expected,
                'error_after_daily_publication': True,
                'required_blockers': ('SEP mutation watermark',)})
        add(name, [bad,
                   step('recover', SECOND)], recovery_from='recover')
    for ticker in ('SPY', 'BIL'):
        fault = Fault(table='SFP', kind='omit_ticker', ticker=ticker)
        bad = step('reference_outage', FIRST, faults=(fault,), ready=False,
                   required_blockers=('frontier benchmark' if ticker == 'SPY' else 'defensive fund marks',))
        field = 'spy' if ticker == 'SPY' else 'defensive'
        bad = bad.model_copy(update={'expected': bad.expected.model_copy(
            update={field: getattr(initial, field)})})
        add(f'missing_reference_{ticker.lower()}',
            [bad,
             step('recover', SECOND)], recovery_from='recover')
    return cases
