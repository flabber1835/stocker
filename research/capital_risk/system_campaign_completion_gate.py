"""Actual canonical packet admission; guard component tests remain distinct."""
from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_completion_scope import TransitionGuard, parse
from system_campaign_completion_facts import contract, evidence, expected_repair, PRIVATE, OVERLAY
from system_campaign_facts import digest
from system_campaign_sprint_facts import qualify_packet_schema, published_packet


def must_refuse(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise ValueError('REFUSED_COMPLETION_GATE_MISSING_' + label)


def qualify(out, cp, old_objects, loaded, codec, cash, request):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from research.pooled_vacancy_funding import backtest
    from sentinel.controller import terminal_returns
    from research.bounded_20y.run import vendor
    from pathlib import Path
    qualify_packet_schema(Packet, request['qualified_packet_source_sha256'])
    c = contract(); source = json.loads((out / PRIVATE).read_bytes())
    actions = inputs.load_actions(Path('/frozen/bundle')); packet_checks = 0; cash_calls = 0
    for event in c['scoped_events']:
        sid = event['security_id']; native = event['native_session']; day = event['session']
        row, = [r for r in source['source_witnesses'] if r['security_id'] == sid]
        prior = SimpleNamespace(median5={'selected': [sid]}, last_processed_session=native,
                    feed={'series': {sid: {'signal_basis_anchor': (native, 1., 1.)}}})
        for session in (native, day):
            packet = Packet(session, (vendor(row),) if session == native else (),
                            {}, {}, 1., {}, tuple(actions.terminal.get(session, ())), ())
            original = digest(asdict(packet)); fixed = packet
            for obj in (*old_objects, loaded):
                fixed = backtest.apply_repair(fixed, obj)
            need(digest(asdict(packet)) == original and fixed.bars == packet.bars,
                 'COMPLETION_GATE_ORIGINAL_PACKETS_AND_QUOTES_UNCHANGED')
            terms = [t for t in fixed.terminal if t.security_id == sid]
            if session == native:
                need(not terms, 'COMPLETION_GATE_PRESERVE_LAST_TRADING_DAY')
                must_refuse(lambda: terminal_returns.values(prior=prior, published=published_packet(packet)),
                            'ORIGINAL_INCOMPLETE_TERMINAL_GUARD')
            else:
                need(len(terms) == 1 and asdict(terms[0]) == event['added'],
                     'COMPLETION_GATE_EXACT_DOCUMENTED_CONSIDERATION')
                result = terminal_returns.values(prior=prior, published=published_packet(fixed))
                need(result[sid] == event['added']['cash_per_share'],
                     'COMPLETION_GATE_CANONICAL_KNOWN_CASH_NOTIONAL')
                cash_calls += 1
            packet_checks += 1
    stale = c['suppression_only']; sid = stale['native']['security_id']
    for expected in (stale['native'], stale['preserved_complete']):
        day = expected['session']; packet = Packet(day, (), {}, {}, 1., {}, tuple(actions.terminal.get(day, ())), ())
        fixed = packet
        for obj in (*old_objects, loaded):
            fixed = backtest.apply_repair(fixed, obj)
        terms = [t for t in fixed.terminal if t.security_id == sid]
        need([asdict(t) for t in terms] == ([] if day == stale['native']['session'] else [stale['preserved_complete']]),
             'COMPLETION_GATE_COWN_SUPPRESS_ONLY_PRESERVES_ONE_COMPLETE_BASE_TERM')
        packet_checks += 1
    # The ordinary component is tested against this actual combined envelope,
    # with every retained input applied. It is not admitted from its unit tests.
    cash.qualify(loaded, old_objects, out / 'october-ordinary-input-qualification.json',
                 packet_source_sha256=request['qualified_packet_source_sha256'])
    body = expected_repair(out, cp['run']['checkpoint_sha256'])
    for cursor, pred in ((cp['source_cursor'], '0' * 64), ('2022-10-04', cp['run']['checkpoint_sha256'])):
        must_refuse(lambda: parse(out / OVERLAY, resume_session=cursor,
                    predecessor_checkpoint_sha256=pred, expected_repair=body,
                    expected_evidence=evidence(out)), 'PREDECESSOR_OR_CONSUMED_CURSOR')
    must_refuse(lambda: codec.original_load(out / OVERLAY, resume_session=cp['source_cursor'],
                 predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256']), 'UNWRAPPED_ORDINARY_SCHEMA')
    # These exercise the real guard implementation with synthetic projections;
    # they are component falsifiers, not canonical strategy/economic calls.
    components = 0
    for when in ('before', 'after'):
        for kind in ('owned', 'ordered'):
            guard = TransitionGuard(codec)
            before = SimpleNamespace(wealth_core={'episodes': {}}, pending=[], state_hash='before')
            after = deepcopy(before); after.state_hash = 'after'
            target = before if when == 'before' else after
            sid = c['scoped_events'][0]['security_id']
            if kind == 'owned': target.wealth_core['episodes']['gate'] = {'security_id': sid}
            else: target.pending = [{'security_id': sid}]
            guard.original_advance = lambda *args: SimpleNamespace(state=after)
            must_refuse(lambda: guard.advance(SimpleNamespace(state=before, input_sha256='0' * 64),
                         SimpleNamespace(session='2022-10-04')), 'POSITION_OR_ORDER_COMPONENT')
            components += 1
    save(out / 'completion-scope-canonical-qualification.json', dict(
        status='ACTUAL_COMBINED_PACKETS_AND_TYPED_INPUT_QUALIFIED', actual_scoped_and_suppress_only_packets=packet_checks,
        actual_scoped_canonical_cash_notional_calls=cash_calls, ordinary_cash_cases=17,
        retained_inputs=len(old_objects), original_packets_and_quotes_unchanged=True,
        suppression_only_complete_term_unchanged=True, predecessor_and_consumed_refused=True,
        unwrapped_ordinary_loader_refused=True, synthetic_guard_component_refusals=components,
        synthetic_components_are_not_economic_transitions=True, financial_sessions_advanced=0,
        production_contacted=False))
