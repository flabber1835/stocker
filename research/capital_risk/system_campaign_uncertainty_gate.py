"""Hosted synthetic canonical-controller qualification; zero market sessions."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from seal import sha256_file
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, CertifiedScalar, growth


def certified_recovery(function, kwargs, bounds):
    checks = []
    supplied = deepcopy(kwargs)
    for key, interval in bounds.items():
        need((kwargs[key] is None) == (interval is None), 'UNCERTAINTY_RETURN_AVAILABILITY')
        if interval is not None:
            supplied[key] = CertifiedScalar(kwargs[key], interval, checks)
    certified = function(**supplied)
    ordinary = function(**deepcopy(kwargs))
    need(certified == ordinary, 'UNCERTAINTY_ACTUAL_COMPLETE_RECOVERY_EQUALITY')
    return ordinary, checks


def qualify(output, request):
    hosted()
    from sentinel.controller import median5, champion_config, terminal_returns
    from research.pooled_input_support import inputs
    from stock_strategy_shared.wealth_core.terminal import TerminalKind
    for name, digest in request['canonical_controller_sources'].items():
        need(sha256_file(Path('/variant') / name) == digest, 'UNCERTAINTY_EXACT_CANONICAL_SOURCE')

    # Verify the real frozen native term is incomplete. Never construct a
    # completed cash term and never call a market/account transition here.
    actions = inputs.load_actions(Path('/frozen/bundle'))
    term, = [v for v in actions.terminal['2019-10-21'] if v.security_id == '941065113449292610']
    need(term.kind is TerminalKind.CASH_MERGER and term.cash_per_share is None
         and not term.completeness(0)[0], 'UNCERTAINTY_ACTUAL_NATIVE_STAYS_INCOMPLETE')
    moved = replace(term, session='2019-10-22')
    prior = SimpleNamespace(median5={'selected': [term.security_id]}, last_processed_session='2019-10-21',
                            feed={'series': {term.security_id: {'signal_basis_anchor': ['2019-10-21', 20., 20.]}}})
    published = SimpleNamespace(session='2019-10-22', terminal_events=[moved], bars=[])
    try:
        terminal_returns.values(prior=prior, published=published)
    except ValueError as exc:
        need(str(exc) == 'incomplete leadership cash terminal: ' + term.security_id,
             'UNCERTAINTY_EXACT_ORIGINAL_REFUSAL')
    else:
        raise ValueError('REFUSED_UNCERTAINTY_ORIGINAL_UNRESOLVED_GUARD')

    # A synthetic rising witness makes the entire [18,20] event range harmless
    # to the actual controller. Exercise the whole 40-session cancellation and
    # subsequent rounding horizon. This is explicitly not historical P02 data.
    state = median5.fresh(champion=True)
    prefix = [1.02 ** n for n in range(41)]
    state.update(last_session='synthetic-000', witness_nav=prefix,
                 selected=['ALDR-SYNTHETIC', 'OTHER-SYNTHETIC'],
                 selected_closes={'ALDR-SYNTHETIC': 20., 'OTHER-SYNTHETIC': 100.})
    proof = RollingWitnessBounds(prefix)
    calls = comparisons = 0
    for day in range(1, 71):
        prices = {'OTHER-SYNTHETIC': state['selected_closes']['OTHER-SYNTHETIC'] * 1.02}
        terminals = {'ALDR-SYNTHETIC'} if day == 1 else set()
        terminal_values = {'ALDR-SYNTHETIC': 18.} if day == 1 else {}
        returns = []
        for sid in state['selected']:
            now = Interval(18., 20.) if sid in terminals else Interval.point(prices[sid])
            returns.append(now.div(Interval.point(state['selected_closes'][sid])).sub(Interval.point(1.)))
        factor = growth(returns)
        state, observed = median5.witness(state, session=f'synthetic-{day:03d}',
            candidates=[SimpleNamespace(security_id='OTHER-SYNTHETIC', recent=1.)], closes=prices,
            terminals=terminals, terminal_values=terminal_values)
        proof.advance(factor, state['witness_nav'][-1])
        bounds = {f'recent_r{n}': proof.period(n) for n in (20, 40)}
        kwargs = dict(state=state, native=1., wc_drawdown=-.05,
                      spy_r20=.02, wc_r20=.01, **observed)
        (state, _), checks = certified_recovery(champion_config.recover, kwargs, bounds)
        need(checks, 'UNCERTAINTY_ACTUAL_COMPARISONS_REQUIRED')
        calls += 1
        comparisons += len(checks)
        if day in (1, 21, 43):
            proof = RollingWitnessBounds.restore(proof.snapshot())

    # An actual source comparison crossing zero must refuse, even if one
    # representative's ordinary outcome would otherwise be valid.
    ambiguous = dict(kwargs, recent_r20=-.01, recent_r40=.1)
    try:
        certified_recovery(champion_config.recover, ambiguous,
                           {'recent_r20': Interval(-.02, .02), 'recent_r40': Interval.point(.1)})
    except ValueError as exc:
        need('AMBIGUOUS_CONTROLLER_COMPARISON' in str(exc), 'UNCERTAINTY_ACTUAL_AMBIGUITY_REFUSAL')
    else:
        raise ValueError('REFUSED_UNCERTAINTY_ACTUAL_COMPARISON_GUARD')

    need(proof.period(40).hi - proof.period(40).lo < 1e-12,
         'UNCERTAINTY_SCALE_CANCELLATION_WITH_ROUNDING')
    save(output, dict(schema='research.system-uncertainty-canonical-gate/1',
        status='SYNTHETIC_CANONICAL_COMPARISONS_QUALIFIED', actual_canonical_recovery_calls=calls,
        invariant_executed_comparisons=comparisons, original_incomplete_terminal_refused=True,
        actual_ambiguous_comparison_refused=True, serialized_math_continuations=3,
        normal_binary64_rounding_bounded=True, uncertainty_range=[18., 20.],
        representative_is_not_a_valuation=True, historical_financial_sessions_advanced=0,
        exact_own_checkpoint_successor_qualified=False, financial_replay_started=False,
        production_contacted=False, canonical_controller_sources=request['canonical_controller_sources']))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    qualify(args.output, json.loads(args.request.read_bytes()))
