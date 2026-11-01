"""Actual hosted parser, canonical settlement, pending-intent and sensor cases."""
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_remainder_input import parse, digest, require_no_position


def refused(function, marker):
    try:
        function()
    except ValueError as error:
        expected = {'OWNED': 'REMAINDER_SENSOR_MUST_NOT_BE_OWNED',
            'ORDERED': 'REMAINDER_SENSOR_MUST_NOT_BE_ORDERED',
            'RECEIVABLE': 'REMAINDER_SENSOR_MUST_NOT_HAVE_OUTSTANDING_ENTITLEMENT',
            'FORWARD_CLAIM': 'REMAINDER_SENSOR_MUST_NOT_HAVE_FORWARD_CASH_CLAIM',
            'AMBIGUOUS_COMPLETE_OUTCOME': 'COMPLETE_CANONICAL_RECOVERY_DIFFERS'}[marker]
        need(expected in str(error), 'REMAINDER_EXACT_COMPONENT_REFUSAL_REASON_' + marker)
        return
    raise ValueError('REFUSED_REMAINDER_GATE_MISSING_' + marker)


def qualify(out, cp, facts, loaded, old_objects, request, *, codec, certificate):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from research.pooled_vacancy_funding import runtime, backtest
    from stock_strategy_shared.wealth_core import v5, adapter
    from stock_strategy_shared.wealth_core.state import PortfolioState, HoldingEpisode
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.engine import Operation
    from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict, apply_terminal
    from system_campaign_sprint_facts import published_packet, qualify_packet_schema
    qualify_packet_schema(Packet, request['qualified_packet_source_sha256'])
    restored = runtime.restore(cp['run'], policy=cp['base']['policy'], input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored) == cp['run'], 'REMAINDER_ACTUAL_STRICT_PARENT_ROUNDTRIP')
    cfg, actions = runtime.config(cp['base']['policy']), inputs.load_actions(Path('/frozen/bundle'))
    checks = []
    for case in facts.catalog['cases']:
        sid, day = case['security_id'], case['core_session']
        for session in sorted({case['native_session'], day}):
            original = Packet(session, (), {}, {}, 1., {}, tuple(actions.terminal.get(session, ())), ())
            before = digest(asdict(original)); fixed = original
            for obj in [*old_objects, loaded]:
                fixed = backtest.apply_repair(fixed, obj)
            matches = [v for v in fixed.terminal if v.security_id == sid]
            need(digest(asdict(original)) == before, 'REMAINDER_ORIGINAL_PACKET_IMMUTABLE')
            if session != day:
                need(not matches, 'REMAINDER_NATIVE_TRADING_DAY_PRESERVED')
            else:
                need(len(matches) == 1, 'REMAINDER_UNIQUE_RECOGNITION_TERM')
                if case['treatment'] != 'CVR_RANGE':
                    need(asdict(matches[0]) == case['added'], 'REMAINDER_EXACT_CANONICAL_ADDED_TERM')
                else:
                    need(not matches[0].completeness(0)[0], 'REMAINDER_CVR_NOT_REPLACED_BY_CASH')
        if case['treatment'] == 'CVR_RANGE':
            continue
        core = PortfolioState.fresh(9000., n_slots=cfg.n_slots,
            entry_sizing_profile=v5.entry_sizing_profile(cfg.economic_profile))
        witness = facts.payload['last_witnesses'][case['ticker']]
        shares = 625 if case['ticker'] == 'DFS' else 10
        core.episodes[0] = HoldingEpisode(sid, case['ticker'], witness['issuer_id'], 0,
            witness['session'], witness['session'], float(witness['raw_close']),
            float(witness['signal_close']), shares, shares,
            episode_peak_split_adjusted_close=float(witness['signal_close']),
            market_sessions_held=17, review_completed=True)
        core.slots[0].occupied_by = sid; ledger = Ledger()
        terms = terminal_terms_from_dict(case['added'])
        basis = {}
        if case['ticker'] == 'DFS':
            delivered = facts.payload['delivered_quote']
            basis = dict(source_signal_to_raw_scale=float(Fraction(witness['signal_close']) / Fraction(witness['raw_close'])),
                delivered_signal_to_raw_scale=float(Fraction(delivered['signal_close']) / Fraction(delivered['raw_close'])),
                delivered_raw_open=float(delivered['raw_open']))
            unchanged = deepcopy((core.to_dict(), ledger.to_dict()))
            missing = apply_terminal(core, terms, ledger=ledger, session=day, cfg=cfg,
                delivered_signal_to_raw_scale=basis['delivered_signal_to_raw_scale'],
                delivered_raw_open=basis['delivered_raw_open'])
            need(missing.get('blocked') is True and missing['reason'] == 'MISSING_CONVERSION_SIGNAL_BASIS',
                 'REMAINDER_DFS_ORIGINAL_MISSING_BASIS_GUARD_REPRODUCED')
            core = PortfolioState.from_dict(unchanged[0]); ledger = Ledger.from_dict(unchanged[1])
        result = apply_terminal(core, terms, ledger=ledger, session=day, cfg=cfg,
            **basis)
        save(out / ('canonical-component-' + case['ticker'] + '.json'), dict(
            fixture_only=True, actual_future_entitlement_claimed=False, terms=case['added'],
            result=result, supplied_basis=basis, financial_sessions_advanced=0))
        need(result['applied'] is True, 'REMAINDER_POSITIVE_CANONICAL_CASE_ACTUALLY_APPLIED')
        if case['ticker'] == 'DFS':
            need(core.cash == 9000. and sum(ep.current_shares for ep in core.episodes.values()) == 637
                 and all(ep.security_id == terms.delivered_security_id for ep in core.episodes.values()),
                 'REMAINDER_DFS_EXACT_WHOLE_SHARE_CONVERSION_WITHOUT_CASH')
            need(not terms.completeness(1)[0], 'REMAINDER_DFS_FRACTION_CANNOT_INVENT_CIL_PRICE')
        else:
            need(core.cash == 9000. + 10. * terms.cash_per_share and not core.episodes
                 and len(ledger.events) == 1, 'REMAINDER_EXACT_COMMON_CASH_REMOVAL')
        once = deepcopy((core.to_dict(), ledger.to_dict()))
        repeat = apply_terminal(core, terms, ledger=ledger, session=day, cfg=cfg)
        need(repeat['reason'] == 'NOT_HELD' and (core.to_dict(), ledger.to_dict()) == once,
             'REMAINDER_ONCE_ONLY_CANONICAL_ENTITLEMENT')
        # Actual V5 pending-dollar cancellation occurs before the fill phase,
        # including when a frozen terminal-day source print remains present.
        empty = PortfolioState.fresh(9000., n_slots=cfg.n_slots,
            entry_sizing_profile=v5.entry_sizing_profile(cfg.economic_profile))
        empty.slots[0].reserved_for = sid
        pending = [adapter.PendingOrder(Operation.OPEN_SLOT_POSITION, sid, case['ticker'],
            0, 0., witness['session'], 'EXPLICIT_DISPOSABLE_TERMINAL_GATE', intended_dollars=1000.)]
        transformed, cancelled = adapter._transform_pending_for_terminal(empty, pending,
            terms=terms, result=dict(applied=False, reason='NOT_HELD', security_id=sid), session=day)
        need(not pending and not transformed and len(cancelled) == 1
             and cancelled[0]['reason'] == 'TERMINATED_BEFORE_FILL',
             'REMAINDER_TERMINATED_V5_INTENT_CANCELLED_BEFORE_LATE_PRINT_FILL')
        checks.append(dict(ticker=case['ticker'], actual_canonical_settlement=True,
            fixture_shares=shares, once_only=True, pending_entry_cancelled=True,
            actual_future_entitlement_claimed=False))
    # Exercise every new sensor adapter against actual canonical term/value and
    # witness functions. These are detached component fixtures, not dated books.
    from sentinel.controller import terminal_returns, median5, champion_config
    from system_campaign_outcome_proof import certified_recovery
    from system_campaign_uncertainty_math import Interval, RollingWitnessBounds
    sensor_checks = []
    with certificate:
        retained_math = certificate.math.snapshot()
        for case in certificate.rcases:
            certificate.math = RollingWitnessBounds.restore(retained_math)
            certificate.pending = None
            sid, day = case['security_id'], case['sensor_session']
            fixture = deepcopy(restored.state)
            fixture.wealth_core['episodes'] = {}; fixture.pending = []
            fixture.ledger['receivables'] = []
            fixture.last_evidence['cash_distributions']['pending'] = []
            fixture.last_processed_session = '2025-04-30'
            fixture.feed['series'][sid] = dict(signal_basis_anchor=('2025-04-30', 100., 100.))
            fixture.median5['selected'] = [sid]; fixture.median5['selected_closes'] = {sid: 100.}
            fixture.median5['last_session'] = '2025-04-30'
            row = facts.payload['event_quotes'][case['ticker']]['row']
            # The publication bar is an explicit detached value object; it is
            # not inserted into the frozen corpus or used for financial replay.
            bars = (SimpleNamespace(security_id=sid, session=day, split_ratio=float(row['split_ratio'])),) if row else ()
            terms = () if case['treatment'] != 'CVR_RANGE' else (
                __import__('dataclasses').replace(codec.natives[sid], session=day),)
            from dataclasses import make_dataclass
            Publication = make_dataclass('DetachedSensorPublication', [('session', str), ('bars', tuple), ('terminal_events', tuple)])
            publication = Publication(day, bars, terms)
            result = terminal_returns.values(prior=fixture, published=publication)
            need(sid in result and certificate.event_bounds is not None,
                 'REMAINDER_ACTUAL_SELECTED_SENSOR_VALUE_AND_RANGE')
            witness, observed = median5.witness(fixture.median5, session=day, candidates=[], closes={},
                terminals=(sid,), terminal_values=result)
            need(witness['selected'] == [] and certificate.bounds is not None,
                 'REMAINDER_ACTUAL_CANONICAL_TERMINAL_WITNESS_AND_EXIT_MEMBERSHIP')
            after, decision = champion_config.recover(state=witness, native=0.,
                wc_drawdown=0., spy_r20=0., wc_r20=0., **observed)
            need(decision['desired_allocation'] == 0.
                 and certificate.pending['comparisons']['all_complete_results_equal'] is True,
                 'REMAINDER_ACTUAL_CANONICAL_FULL_OUTCOME_PROOF_FOR_NEW_RANGE')
            sensor_checks.append(dict(ticker=case['ticker'], signal_interval=certificate.event_bounds.pair(),
                actual_canonical_value_and_witness=True, new_membership_excluded=True))
            for mutation, marker in (
                (lambda value: value.wealth_core['episodes'].update({'0': {'security_id': sid}}), 'OWNED'),
                (lambda value: value.pending.append({'security_id': sid}), 'ORDERED'),
                (lambda value: value.ledger['receivables'].append({'security_id': sid}), 'RECEIVABLE'),
                (lambda value: value.last_evidence['cash_distributions']['pending'].append({'security_id': sid}), 'FORWARD_CLAIM')):
                changed = deepcopy(fixture); mutation(changed)
                refused(lambda: require_no_position(changed, sid), marker)
            # Do not retain a detached component witness in the financial seed.
            certificate.pending = None
        latent = median5.fresh(champion=True)
        latent.update(last_session='2026-07-24', episode=True, latched=False, full_streak=0,
            recent_positive_streak=0, previous_native=1., previous_desired=0., effective_native=1.)
        latent_kwargs = dict(state=latent, native=1., wc_drawdown=-.05,
            recent_r20=-.01, recent_r40=.01, spy_r20=-.03, wc_r20=-.02)
        refused(lambda: certified_recovery(certificate.original_recover, latent_kwargs,
            dict(recent_r20=Interval(-.01, .01), recent_r40=Interval.point(.01))), 'AMBIGUOUS_COMPLETE_OUTCOME')
    need(terminal_returns.values is certificate.original_values
         and median5.witness is certificate.original_witness
         and champion_config.recover is certificate.original_recover,
         'REMAINDER_QUALIFICATION_HOOKS_RESTORED')
    # The actual certificate used for economics is constructed afresh by caller.
    need(runtime.checkpoint(restored) == cp['run'], 'REMAINDER_QUALIFICATION_PARENT_UNCHANGED')
    save(out / 'remainder-terminal-canonical-qualification.json', dict(
        schema='research.p02-remainder-terminal-qualification/1', status='QUALIFIED',
        parent_checkpoint_sha256=cp['sha256'], canonical_actions=checks, sensor_cases=sensor_checks,
        actual_parser_and_packet_cases=True, actual_parent_roundtrip=True,
        actual_scope_refusal_cases=4 * len(sensor_checks), financial_sessions_advanced=0,
        actual_resumed_session_proof_still_required=True, production_contacted=False))
