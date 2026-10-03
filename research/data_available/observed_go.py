"""Offline replay of an observed GO anomaly; all unaffected prices are synthetic.

No production modules are changed. Run --coverage-control with PYTHONPATH set
to an archive of the deployed commit to reproduce its original refusal.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace


FIXTURE = Path(__file__).with_name('fixtures') / 'go-20260930.json'


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding='utf8'))


def renamed(fixture):
    """Same pattern under unrelated names and native identities."""
    result = deepcopy(fixture)
    listings = result['probe']['tickers']['rows']
    symbols = {r['ticker']: f'ALTERNATE{i}' for i, r in enumerate(listings)}
    for i, row in enumerate(listings):
        row['permaticker'] = 9900000 + i
        row['ticker'] = symbols[row['ticker']]
        row['relatedtickers'] = symbols[row['relatedtickers']]
    for row in result['probe']['sep']['rows']:
        row['ticker'] = symbols[row['ticker']]
    for row in result['probe']['actions']['rows']:
        row['ticker'] = symbols[row['ticker']]
        row['contraticker'] = symbols[row['contraticker']]
    return result


def identity(fixture):
    from sentinel.feed.symbol_identity import SymbolProjection
    probe = fixture['probe']
    return SymbolProjection(csv_listings(fixture), probe['actions']['rows'],
                            through=probe['requested_interval'][-1])


def csv_listings(fixture):
    # The diagnostic JSON uses numbers; the deployed bulk CSV uses text IDs.
    return [{**row, 'permaticker':str(row['permaticker'])}
            for row in fixture['probe']['tickers']['rows']]


def coverage_control(fixture):
    from sentinel.feed.source_authority import (
        SeedCoverageAccumulator, SeedListingProjection, SourceAuthorityRefused)
    from sentinel.feed.source_authority import coverage
    from sentinel.feed.symbol_identity import SymbolProjection

    expected = fixture['bundle']['source_coverage']
    session = expected['session']
    observed = fixture['probe']
    listings = csv_listings(fixture)
    extra = expected['expected_eligible'] - len(listings)
    rows = [r for r in observed['sep']['rows'] if r['date'] == session]
    for i in range(extra):
        ticker = f'CONTROL{i:04d}'
        listings.append(dict(table='SEP', permaticker=8000000+i, ticker=ticker,
            category='Domestic Common Stock Primary Class',
            firstpricedate='2020-01-02', lastpricedate='2026-09-29'))
        rows.append(dict(ticker=ticker, date=session, open=50., close=50.,
                         closeunadj=50., volume=1_000_000.))
    projection = SymbolProjection(listings, observed['actions']['rows'],
                                  through=observed['requested_interval'][-1])
    accumulator = SeedCoverageAccumulator(
        SeedListingProjection(listings, source_digest='0'*64),
        projection.resolver().resolve)
    try:
        for row in rows:
            accumulator.add(row)
        try:
            accumulator.require_complete(date_from=session, date_to=session)
        except SourceAuthorityRefused as exc:
            evidence = json.loads(str(exc).split(': ', 1)[1])
            error_type = type(exc).__name__
        else:
            raise AssertionError('coverage control did not reproduce refusal')
    finally:
        accumulator.close()
    fields = ('session', 'expected_eligible', 'received_eligible',
              'missing_eligible_total', 'missing_eligible',
              'unexpected_eligible_total', 'unresolved_source_tickers')
    assert {k:evidence[k] for k in fields} == {k:expected[k] for k in fields}
    assert evidence['identity_diagnostics'] == expected['identity_diagnostics']
    return dict(status='REFUSAL_REPRODUCED', synthetic_unaffected_listings=extra,
                observed_listings=len(observed['tickers']['rows']),
                error_type=error_type,
                evidence=evidence,
                coverage_source_sha256=hashlib.sha256(
                    Path(coverage.__file__).read_bytes()).hexdigest())


def snapshot_case(fixture, day, *, include_anomaly=True):
    from sentinel.feed.calendar import previous_sessions
    from stock_strategy_shared.wealth_core.feed import (
        SecurityMeta, VendorBar, to_daily_bar)
    from research.data_available.snapshot import from_window

    # A fixed absolute index ensures rolling windows share identical controls.
    full_axis = previous_sessions(fixture['probe']['requested_interval'][-1], 305)
    indices = {d:i for i, d in enumerate(full_axis)}
    axis = previous_sessions(day, 300)
    metadata, rows = {}, []
    for k in range(30):
        sid, ticker = f'CONTROL-{k:02d}', f'CONTROL{k:02d}'
        metadata[sid] = SecurityMeta(sid, ticker,
            category='Domestic Common Stock Primary Class', permaticker=sid,
            first_session=full_axis[0])
        for d in axis:
            i = indices[d]
            price = 50*math.exp(.001*i+.025*math.sin(i*.37+k))
            rows.append(VendorBar(d, sid, ticker, price, price, 1_000_000.,
                                  signal_close=price))
    if include_anomaly:
        resolver = identity(fixture).resolver()
        for row in fixture['probe']['tickers']['rows']:
            sid = str(row['permaticker'])
            metadata[sid] = SecurityMeta(sid, row['ticker'],
                category=row['category'], permaticker=sid,
                first_session=row['firstpricedate'],
                last_session=row['lastpricedate'],
                related_tickers=(row['relatedtickers'],))
        for row in fixture['probe']['sep']['rows']:
            if row['date'] not in axis:
                continue
            sid = resolver.resolve(row['ticker'], row['date'])
            assert sid is not None
            rows.append(VendorBar(row['date'], sid, row['ticker'],
                row['closeunadj'], row['open'], row['volume'],
                signal_close=row['close']))
    signals, feed = from_window(axis, rows, metadata)
    norm = SimpleNamespace(bars=tuple(to_daily_bar(row, feed.series[row.security_id])
                                     for row in rows if row.session == day))
    return signals, feed, norm


def replay(fixture):
    from sentinel.feed.calendar import sessions_in_range
    from research.data_available.run import Arm

    affected = {str(r['permaticker']) for r in fixture['probe']['tickers']['rows']}
    test, control = Arm('snapshot'), Arm('snapshot')
    diagnostics = []
    for day in sessions_in_range(*fixture['probe']['requested_interval']):
        signals, feed, norm = snapshot_case(fixture, day)
        reference, _, clean_norm = snapshot_case(fixture, day, include_anomaly=False)
        assert [b for b in signals if b.security_id not in affected] == reference
        assert not any(b.eligible for b in signals if b.security_id in affected)
        result = test.step(day, norm, signals)
        clean = control.step(day, clean_norm, reference)
        assert result == clean
        assert test.state.to_dict() == control.state.to_dict()
        assert test.pending == control.pending
        assert test.ledger.to_dict() == control.ledger.to_dict()
        assert not (set(result['held']) & affected)
        diagnostics.append(dict(session=day, blocked=result['blocked'],
            equity=result['equity'], queued=result['queued'], fills=result['fills'],
            eligible=result['eligible'], affected_rows={sid:len(feed.series[sid].sessions)
                if sid in feed.series else 0 for sid in sorted(affected)}))
    assert diagnostics[0]['queued'] > 0
    assert sum(r['fills'] for r in diagnostics) > 0
    assert not any(r['blocked'] for r in diagnostics)
    return dict(status='PASS', variant='snapshot', synthetic_mature_candidates=30,
                identical_state_orders_ledger=True, sessions=diagnostics)


def held_gap(fixture):
    from stock_strategy_shared.wealth_core.state import HoldingEpisode
    from research.data_available.run import Arm

    day = fixture['bundle']['source_coverage']['session']
    # Choose by metadata/gap, never by a ticker-specific branch.
    present = {r['ticker'] for r in fixture['probe']['sep']['rows'] if r['date']==day}
    listing, = [r for r in fixture['probe']['tickers']['rows'] if r['ticker'] not in present]
    sid, ticker = str(listing['permaticker']), listing['ticker']
    arm = Arm('snapshot')
    arm.state.episodes[0] = HoldingEpisode(sid, ticker, f'SID:{sid}', 0,
        '2026-09-23', day, 10., 10., 100., 100.)
    arm.state.slots[0].occupied_by = sid
    arm.state.initialized = True
    arm.state.cash -= 1000.
    signals, _, norm = snapshot_case(fixture, day)
    result = arm.step(day, norm, signals)
    assert result['blocked'] and result['equity'] is None
    assert result['queued'] == result['fills'] == 0
    assert arm.state.held_security_ids() == {sid}
    assert arm.state.episodes[0].current_shares == 100.
    assert arm.state.cash == 49000.
    assert not arm.report()['performance_available']
    return dict(status='PASS', scenario='hypothetical held affected security',
                identity=sid, shares=100, cash=arm.state.cash,
                blocked=True, equity=None, queued=0, fills=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--coverage-control', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    fixture = load_fixture()
    if args.coverage_control:
        result = coverage_control(fixture)
    else:
        result = dict(unheld=replay(fixture), held=held_gap(fixture),
                      renamed_unheld=replay(renamed(fixture)),
                      renamed_held=held_gap(renamed(fixture)))
    result['fixture_sha256'] = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    result['bundle_sha256'] = fixture['bundle']['sha256']
    payload = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf8') as output:
            output.write(payload)
        print(f'Results written to {args.output}')
    else:
        print(payload, end='')


if __name__ == '__main__':
    main()
