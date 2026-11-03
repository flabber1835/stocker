"""Actual KDNY packets and four-event canonical proof; zero market sessions."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest
from system_campaign_chinook_input import SID, NATIVE, DAY, parse
from system_campaign_chinook_facts import PRIVATE, evidence
from system_campaign_chinook_sensor import SensorCertificate, PriorCertificate, check_inherited
from system_campaign_uncertainty_math import Interval, RollingWitnessBounds, growth
from system_campaign_uncertainty_gate import certified_recovery


def must_refuse(function, label):
    try:
        function()
    except ValueError:
        return
    raise ValueError('REFUSED_CHINOOK_MISSING_' + label)


def four_event_recovery():
    """Exercise the unchanged real witness/recovery functions, not P02 returns."""
    hosted()
    from sentinel.controller import median5, champion_config
    names = ['ALDR', 'ZGNX', 'ABMD', SID, 'OTHER']
    events = {1: ('ALDR', 18., 20.), 12: ('ZGNX', 26., 28.),
              24: ('ABMD', 380., 415.), 36: (SID, 40., 44.)}
    state = median5.fresh(champion=True)
    prefix = [1.02**number for number in range(41)]
    state.update(last_session='joint-000', witness_nav=prefix, selected=names,
                 selected_closes={'ALDR': 20., 'ZGNX': 28. / 1.02**11,
                                  'ABMD': 415. / 1.02**23, SID: 44. / 1.02**35, 'OTHER': 100.})
    math = RollingWitnessBounds(prefix)
    calls = comparisons = restorations = 0
    for day in range(1, 81):
        event = events.get(day)
        terminals = {event[0]} if event else set()
        prices = {sid: state['selected_closes'][sid] * 1.02
                  for sid in state['selected'] if sid not in terminals}
        terminal_values = {event[0]: event[1]} if event else {}
        returns = []
        for sid in state['selected']:
            value = Interval(event[1], event[2]) if event and sid == event[0] else Interval.point(prices[sid])
            returns.append(value.div(Interval.point(state['selected_closes'][sid])).sub(Interval.point(1.)))
        members = [sid for sid in names
                   if not any(sid == item[0] and date <= day for date, item in events.items())]
        state, observed = median5.witness(state, session=f'joint-{day:03d}',
            candidates=[SimpleNamespace(security_id=sid, recent=1.) for sid in members],
            closes=prices, terminals=terminals, terminal_values=terminal_values)
        math.advance(growth(returns), state['witness_nav'][-1])
        bounds = {f'recent_r{period}': math.period(period) for period in (20, 40)}
        kwargs = dict(state=state, native=1., wc_drawdown=-.05, spy_r20=.02, wc_r20=.01, **observed)
        (state, _), checks = certified_recovery(champion_config.recover, kwargs, bounds)
        calls += 1
        comparisons += len(checks)
        if day in (2, 13, 25, 37, 55):
            saved = math.snapshot()
            math = RollingWitnessBounds.restore(saved)
            need(math.snapshot() == saved, 'CHINOOK_EXACT_FOUR_EVENT_SERIALIZED_CONTINUATION')
            restorations += 1
    ambiguous = dict(kwargs, recent_r20=-.01, recent_r40=.1)
    try:
        certified_recovery(champion_config.recover, ambiguous,
                           {'recent_r20': Interval(-.02, .02), 'recent_r40': Interval.point(.1)})
    except ValueError as error:
        need('AMBIGUOUS_CONTROLLER_COMPARISON' in str(error), 'CHINOOK_ACTUAL_CROSSING_REFUSAL')
    else:
        raise ValueError('REFUSED_CHINOOK_COMPARISON_GUARD_MISSING')
    return dict(actual_canonical_recovery_calls=calls, invariant_comparisons=comparisons,
                serialized_joint_continuations=restorations, uncertain_events=4,
                actual_crossing_refused=True)


def qualify(out, cp, objects, loaded, codec, request):
    hosted()
    check_inherited()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from sentinel.core.session import PublishedSession
    from sentinel.controller import terminal_returns
    from research.pooled_vacancy_funding import backtest
    from research.bounded_20y.run import vendor
    from system_campaign_sprint_facts import qualify_packet_schema
    qualify_packet_schema(Packet, request['qualified_packet_source_sha256'])
    source = json.loads((out / PRIVATE).read_bytes())
    actions = inputs.load_actions(Path('/frozen/bundle'))
    last, = [row for row in source['source_witnesses'] if row['session'] == NATIVE]
    bar = vendor(last)
    native = codec.native
    fixed = {}
    for day in (NATIVE, DAY):
        packet = Packet(day, (bar,) if day == NATIVE else (), {}, {}, 1., {},
                        tuple(actions.terminal.get(day, ())), ())
        original = digest(asdict(packet))
        value = packet
        for obj in [*objects, loaded]:
            value = backtest.apply_repair(value, obj)
        need(digest(asdict(packet)) == original and value.bars == packet.bars,
             'CHINOOK_ORIGINAL_PACKET_AND_QUOTES_PRESERVED')
        matches = [term for term in value.terminal if term.security_id == SID]
        need(matches == ([] if day == NATIVE else [replace(native, session=DAY)]),
             'CHINOOK_ACTUAL_CANONICAL_RECALENDAR')
        fixed[day] = value
    prior = SimpleNamespace(wealth_core={'episodes': {}}, pending=[], median5={'selected': [SID]},
        last_processed_session=NATIVE,
        feed={'series': {SID: {'signal_basis_anchor':
                             [NATIVE, float(last['raw_close']), float(last['signal_close'])]}}})
    published = PublishedSession(session=DAY, data_version=1, bars=(), meta={}, sectors={},
                                 spy_closeadj=[1.], terminal_events=fixed[DAY].terminal)
    try:
        terminal_returns.values(prior=prior, published=published)
    except ValueError as error:
        need(str(error) == 'incomplete leadership cash terminal: ' + SID,
             'CHINOOK_ORIGINAL_CANONICAL_REFUSAL')
    else:
        raise ValueError('REFUSED_CHINOOK_ORDINARY_GUARD_MISSING')
    probe = SensorCertificate.__new__(SensorCertificate)
    probe.ccodec, probe.cnative, probe.csource = codec, native, source
    probe.original_values = terminal_returns.values
    values = probe.values(prior=prior, published=published)
    need(values[SID] == probe.event_bounds.lo and probe.cbasis['selected'], 'CHINOOK_ACTUAL_SENSOR_GATE')
    for changed in (
        SimpleNamespace(**{**vars(prior), 'wealth_core': {'episodes': {'x': {'security_id': SID}}}}),
        SimpleNamespace(**{**vars(prior), 'pending': [{'security_id': SID}]}),
    ):
        must_refuse(lambda: probe.values(prior=changed, published=published), 'OWNED_OR_PENDING_VALUE_GUARD')
    # Actual new post-state guard, plus its removal falsifier through the
    # unchanged parent method. No canonical market transition is performed.
    owned_after = SimpleNamespace(wealth_core={'episodes': {'x': {'security_id': SID}}}, pending=[])
    probe.math = None
    probe.original_advance = lambda run, packet: SimpleNamespace(state=owned_after)
    run = SimpleNamespace(state=prior)
    must_refuse(lambda: probe.advance(run, published), 'ACTUAL_POST_STATE_GUARD')
    need(PriorCertificate.advance(probe, run, published).state is owned_after,
         'CHINOOK_ACTUAL_POST_GUARD_REMOVAL_FALSIFIER')
    for cursor, predecessor in ((cp['source_cursor'], '0' * 64), (NATIVE, cp['run']['checkpoint_sha256'])):
        must_refuse(lambda: parse(out / 'chinook-sensor-input.json', resume_session=cursor,
                    predecessor_checkpoint_sha256=predecessor, expected_evidence=evidence(out),
                    native_sha256=codec.native_sha256), 'PREDECESSOR_OR_CONSUMED_DATE')
    must_refuse(lambda: codec.original_load(out / 'chinook-sensor-input.json',
                resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256']),
                'UNWRAPPED_ORDINARY_LOADER')
    joint = four_event_recovery()
    save(out / 'chinook-canonical-qualification.json', dict(
        status='ACTUAL_PACKETS_AND_FOUR_EVENT_CANONICAL_GATE_PASSED',
        actual_packets=2, retained_inputs=len(objects), original_incomplete_term_refused=True,
        original_packets_and_quotes_preserved=True, actual_owned_and_pending_refusals=True,
        actual_post_state_and_guard_removal_falsifier=True, ordinary_parser_refused=True,
        wrong_predecessor_and_consumed_refused=True, **joint,
        financial_sessions_advanced=0, production_contacted=False))
