"""Hosted actual packets and canonical unheld no-op; no financial sessions."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import json
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest
from system_campaign_close_facts import contract, PRIVATE
from system_campaign_close_scope import require_absent, require_intents
from system_campaign_sprint_facts import published_packet, qualify_packet_schema
from system_campaign_2021_completions_facts import require_witness


def qualify(out, cp, loaded, old_objects, request):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from research.bounded_20y.run import vendor
    from research.pooled_vacancy_funding import backtest, runtime
    from sentinel.controller import terminal_returns
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict, apply_terminal
    c = contract();event = c['event'];sid = event['security_id'];day = event['session']
    qualify_packet_schema(Packet, request['qualified_packet_source_sha256'])
    payload = json.loads((out / PRIVATE).read_bytes())
    rows = {(v['session'], v['security_id']): v for v in payload['source_witnesses']}
    source = vendor(rows[event['native_session'], sid])
    delivered = vendor(rows[day, event['added']['delivered_security_id']])
    prior = SimpleNamespace(median5={'selected': [sid]}, last_processed_session=event['native_session'],
        feed={'series': {sid: {'signal_basis_anchor': (event['native_session'], source.raw_close, source.signal_close)}}})
    actions = inputs.load_actions('/frozen/bundle');packets = 0;incomplete = 0
    for session in (event['native_session'], day):
        original = Packet(session, (source,) if session == event['native_session'] else (delivered,),
                          {}, {}, 1., {}, tuple(actions.terminal.get(session, ())), ())
        before = digest(asdict(original));fixed = original
        for obj in [*old_objects, loaded]: fixed = backtest.apply_repair(fixed, obj)
        need(digest(asdict(original)) == before and fixed.bars == original.bars,
             'CLOSE_GATE_ORIGINAL_PACKET_AND_QUOTES_UNCHANGED')
        packets += 1;matches = [v for v in fixed.terminal if v.security_id == sid]
        if session == event['native_session']:
            need(not matches and terminal_returns.values(prior=prior, published=published_packet(fixed)) == {},
                 'CLOSE_GATE_PRESERVED_ACTUAL_LAST_TRADING_DAY')
            try: terminal_returns.values(prior=prior, published=published_packet(original))
            except ValueError as exc:
                need('incomplete leadership cash terminal' in str(exc), 'CLOSE_GATE_ORIGINAL_REFUSAL_REASON');incomplete += 1
            else: raise ValueError('REFUSED_CLOSE_GATE_ORIGINAL_INCOMPLETE_GUARD')
            bad = replace(original, terminal=tuple(v for v in original.terminal if v.security_id != sid))
            try: backtest.apply_repair(bad, loaded)
            except ValueError: pass
            else: raise ValueError('REFUSED_CLOSE_GATE_MISSING_NATIVE_SOURCE')
        else:
            term, = matches
            need(asdict(term) == event['added'] and term.completeness(0)[0]
                 and not term.completeness(1)[0], 'CLOSE_GATE_EXACT_CLOSING_TERM_WITHOUT_OWNED_CIL_MODEL')
            actual = terminal_returns.values(prior=prior, published=published_packet(fixed))[sid]
            expected = float((Fraction('30') + Fraction('0.03002')*Fraction(str(delivered.raw_close)))
                             * Fraction(str(source.signal_close))/Fraction(str(source.raw_close)))
            need(actual == expected, 'CLOSE_GATE_CANONICAL_EXACT_SIGNAL_SCALED_CLOSING_CONSIDERATION')
            try: terminal_returns.values(prior=prior,
                published=SimpleNamespace(session=day, bars=(), terminal_events=fixed.terminal))
            except ValueError as exc: need('lacks delivered close' in str(exc), 'CLOSE_GATE_MISSING_DELIVERED_CLOSE_REASON')
            else: raise ValueError('REFUSED_CLOSE_GATE_MISSING_DELIVERED_CLOSE')
    witness = event['delivered_witness']
    try: require_witness({**rows[day, witness['security_id']], 'issuer_id': 'WRONG'}, witness)
    except ValueError: pass
    else: raise ValueError('REFUSED_CLOSE_GATE_CHANGED_DELIVERED_IDENTITY')
    restored = runtime.restore(cp['run'], policy=cp['base']['policy'], input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored) == cp['run'], 'CLOSE_GATE_EXACT_OWN_CANONICAL_ROUNDTRIP')
    original_state = deepcopy(restored.state.wealth_core)
    require_absent(original_state, restored.state.pending, [sid])
    require_intents(restored.state.last_evidence['wealth_core']['intents'], [sid])
    core = PortfolioState.from_dict(deepcopy(original_state));ledger = Ledger()
    before = (core.to_dict(), ledger.to_dict());terms = terminal_terms_from_dict(event['added'])
    result = apply_terminal(core, terms, ledger=ledger, session=day, cfg=runtime.config(cp['base']['policy']))
    need(result['applied'] is False and result['reason'] == 'NOT_HELD'
         and (core.to_dict(), ledger.to_dict()) == before, 'CLOSE_GATE_CANONICAL_UNHELD_NO_CASH_DELIVERY_OR_CIL')
    for kind in ('OWNED', 'ORDERED', 'INTENT'):
        bad_core = deepcopy(original_state);pending = [];intents = []
        if kind == 'OWNED': bad_core['episodes']['forced-scope-falsifier'] = {'security_id': sid}
        elif kind == 'ORDERED': pending = [{'security_id': sid}]
        else: intents = [{'security_id': sid}]
        try:
            require_absent(bad_core, pending, [sid]);require_intents(intents, [sid])
        except ValueError: pass
        else: raise ValueError('REFUSED_CLOSE_GATE_' + kind + '_SCOPE_GUARD')
    need(restored.state.wealth_core == original_state and runtime.checkpoint(restored) == cp['run'],
         'CLOSE_GATE_OWN_PARENT_NEVER_MUTATED_OR_ADVANCED')
    save(out / 'close-canonical-qualification.json', dict(status='ACTUAL_PACKETS_AND_UNHELD_CLOSE_SCOPE_QUALIFIED',
        parent_checkpoint_sha256=cp['sha256'], original_portfolio_sha256=digest(original_state),
        actual_packet_checks=packets, original_incomplete_guards=incomplete,
        exact_closing_signal_consideration=expected, actual_parent_roundtrip=True,
        actual_unheld_noop=True, no_cash_in_lieu_price_selected=True, preopen_completion_claimed=False,
        missing_native_and_delivery_quote_refused=True, changed_delivery_identity_refused=True,
        owned_pending_intent_guard_falsifiers=True, source_state_unchanged=True,
        qualification_copy_only=True, actual_resumed_window_proof_still_required=True,
        financial_sessions_advanced=0, production_contacted=False))
