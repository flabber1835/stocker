"""Read-only delegates around actual P10 canonical action/risk/sensor calls."""
from copy import deepcopy
from fractions import Fraction
import inspect
from pathlib import Path

from system_campaign_p10_ahl2_contract import SID, AFFECTED, NATIVE, POLICY, need, digest, sha
from system_campaign_p10_ahl2_input import document_bytes, packet_change


def cash_postcondition(before, after, ledger_before, ledger_after, terms, result):
    held = [(k,v) for k,v in sorted(before['episodes'].items(), key=lambda x:int(x[0])) if v['security_id'] == SID]
    if not held:
        need(result['reason'] == 'NOT_HELD' and before == after and ledger_before == ledger_after,
             'P10_ACTUAL_UNHELD_CASH_APPLICATION_IS_EXACT_NOOP')
        return dict(actual_held=False, episode_count=0, nominal_cash=0.0)
    expected_cash = before['cash']
    expected = []
    for slot, ep in held:
        proceeds = ep['current_shares'] * terms['cash_per_share']
        expected_cash += proceeds
        expected.append((ep['current_shares'], proceeds))
    events = ledger_after['events'][len(ledger_before['events']):]
    need(ledger_after['events'][:len(ledger_before['events'])] == ledger_before['events']
         and len(events) == len(held) and result['applied'] is True
         and after['cash'] == expected_cash and not any(v['security_id'] == SID for v in after['episodes'].values()),
         'P10_CANONICAL_EPISODE_ORDER_CASH_AND_COMPLETE_TERMINAL_REMOVAL')
    for (shares, proceeds), event in zip(expected, events):
        need(event['event_type'] == 'CASH_MERGER' and event['security_id'] == SID
             and event['price'] == 42.75 and event['cash_delta'] == proceeds
             and event['shares_delta'] == -shares and event['detail']['shares'] == shares
             and event['detail']['reference'] == terms['reference'], 'P10_EACH_ACTUAL_EXACT_CONTRACTUAL_CASH_LEDGER_POST')
    running_cash = before['cash']
    for (_, proceeds), event in zip(expected, events):
        need(event['fees'] == 0.0 and event['cash_before'] == running_cash
             and event['cash_after'] == running_cash + proceeds, 'P10_EXACT_LEDGER_CASH_BIN_ADDITION_ORDER_AND_ZERO_TERMINAL_FEES')
        running_cash += proceeds
    need({k:v for k,v in before['episodes'].items() if v['security_id'] != SID} == after['episodes']
         and ledger_before.get('receivables', []) == ledger_after.get('receivables', []),
         'P10_UNRELATED_EPISODES_AND_ALL_RECEIVABLES_PRESERVED_BY_CASH_ACTION')
    for slot, ep in held:
        need(after['slots'][str(slot)]['occupied_by'] is None, 'P10_ACTUAL_CASH_RELEASES_EACH_SOURCE_SLOT')
    need(SID not in after.get('terminal_pending_sessions', {})
         and SID not in after.get('terminal_pending_terms', {}), 'P10_SOURCE_PENDING_TERMS_EXTINGUISHED')
    return dict(actual_held=True, episode_count=len(held), actual_quantities=[x[0] for x in expected],
                nominal_cash=sum(x[1] for x in expected), ledger_events=len(events),
                cash_operation_order='CANONICAL_SORTED_SLOT_MULTIPLY_THEN_SEQUENTIAL_ADD')


class Observer:
    """No hook changes an argument, return value, exception or canonical source."""
    def __init__(self, binding):
        self.binding = binding
        self.spec = binding.spec
        self.saved = []
        self.current = None
        self.records = []
        self.packet_records = []
        self.packet_samples = {}
        self.risk_sample = None

    def patch(self, owner, name, replacement):
        old = getattr(owner, name)
        self.saved.append((owner, name, old))
        setattr(owner, name, replacement)
        return old

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest
        from stock_strategy_shared.wealth_core import capital_risk, terminal, adapter
        from sentinel.controller import terminal_returns
        from system_campaign_discovery_context import material
        self.material = material
        try:
            self.original_repair = self.patch(backtest, 'apply_repair', self.repair)
            self.original_terminal = self.patch(terminal, 'apply_terminal', self.terminal)
            self.original_risk = self.patch(capital_risk, 'volatility_stop', self.risk)
            self.original_decide = self.patch(adapter, 'decide', self.decide)
            self.original_values = self.patch(terminal_returns, 'values', self.values)
        except BaseException:
            self.restore()
            raise
        return self

    def restore(self):
        for owner, name, value in reversed(self.saved):
            setattr(owner, name, value)
        self.saved.clear()

    def __exit__(self, *args):
        self.restore()

    def repair(self, packet, obj):
        before = self.material(packet)
        result = self.original_repair(packet, obj)
        if self.binding.new_input and obj.sha256 == sha(document_bytes(self.spec)):
            proof = packet_change(packet, result, spec=self.spec, material=self.material)
            need(self.material(packet) == before, 'P10_CANONICAL_REPAIR_NEVER_MUTATES_SOURCE_PACKET')
            if packet.day >= self.spec['next_session'] and packet.day <= AFFECTED:
                self.packet_records.append(proof)
            if packet.day in (NATIVE, AFFECTED):
                self.packet_samples[packet.day] = deepcopy(packet)
        return result

    def begin(self, run, publication):
        from research.pooled_vacancy_funding import runtime
        need(self.current is None, 'P10_OBSERVER_ONE_CANONICAL_SESSION_AT_A_TIME')
        self.current = dict(session=publication.session, prior=deepcopy(runtime.checkpoint(run)),
            publication=self.material(publication), publication_sha256=digest(self.material(publication)),
            terminal=[], risk=[], engines=[], sensors=[], order=[])

    def terminal(self, state, terms, **kwargs):
        if self.current is None or terms.security_id != SID or terms.session != AFFECTED:
            return self.original_terminal(state, terms, **kwargs)
        before, ledger_before = deepcopy(state.to_dict()), deepcopy(kwargs['ledger'].to_dict())
        caller = inspect.currentframe().f_back
        actual = caller.f_code.co_name == 'apply_terminal' and caller.f_locals.get('state') is state
        result = self.original_terminal(state, terms, **kwargs)
        record = dict(actual_context_call=actual, before=before, after=deepcopy(state.to_dict()),
            ledger_before=ledger_before, ledger_after=deepcopy(kwargs['ledger'].to_dict()),
            terms=self.material(terms), result=self.material(result), phase=kwargs.get('phase', 'OPEN'))
        record['postcondition'] = cash_postcondition(record['before'], record['after'],
            record['ledger_before'], record['ledger_after'], record['terms'], record['result'])
        need(record['phase'] == 'OPEN', 'P10_CONTRACTUAL_CASH_AVAILABLE_ONLY_ACTUAL_OPEN_ACTION_PHASE')
        self.current['terminal'].append(record)
        self.current['order'].append('ACTUAL_TERMINAL' if actual else 'PROBE_TERMINAL')
        return result

    def decide(self, **kwargs):
        if self.current is None:
            return self.original_decide(**kwargs)
        before = deepcopy(kwargs['state'].to_dict())
        eligible = [(int(slot), ep['security_id']) for slot,ep in sorted(before['episodes'].items(), key=lambda x:int(x[0]))
                    if not ep['exit_pending']]
        offset = len(self.current['risk'])
        self.current['order'].append('ENGINE_BEGIN')
        result = self.original_decide(**kwargs)
        observed = [(x['slot_id'], x['security_id']) for x in self.current['risk'][offset:]]
        need(observed == eligible, 'P10_EVERY_SURVIVING_NONEXITING_EPISODE_TRAVERSES_ORIGINAL_V_GUARD')
        self.current['engines'].append(dict(before=before, eligible=eligible, risk_calls=observed,
            result=self.material(result), original_native_guard_invoked_for_every_eligible_episode=True))
        self.current['order'].append('ENGINE_RETURN')
        return result

    def risk(self, ep, *, bars, session, cfg):
        before = deepcopy(ep)
        bar = next((x for x in bars if x.security_id == ep.security_id), None)
        if self.risk_sample is None and bar is not None:
            self.risk_sample = (deepcopy(ep), deepcopy(bar), session, cfg)
        try:
            result = self.original_risk(ep, bars=bars, session=session, cfg=cfg)
        except BaseException as error:
            if self.current is not None:
                self.current['risk'].append(dict(security_id=ep.security_id, slot_id=ep.slot_id,
                    before=self.material(before), bar=self.material(bar), error=str(error)))
            raise
        if self.current is not None:
            from sentinel.feed.calendar import previous_sessions
            axis = previous_sessions(session, 21)
            need(cfg.economic_profile == POLICY and bar is not None
                 and list(bar.signal_sessions or ()) == axis and len(bar.closes) >= 21,
                 'P10_ACTUAL_UNCHANGED_NATIVE21_DATES_AND_CLOSES')
            self.current['risk'].append(dict(security_id=ep.security_id, slot_id=ep.slot_id,
                before=self.material(before), after=self.material(ep), bar=self.material(bar),
                axis=axis, result=result, original_guard_delegated=True))
        return result

    def values(self, *, prior, published):
        result = self.original_values(prior=prior, published=published)
        if self.current is not None and published.session == AFFECTED:
            selected = SID in prior.median5['selected']
            expected = None
            if selected:
                anchor = prior.feed['series'][SID]['signal_basis_anchor']
                need(anchor[0] == prior.last_processed_session, 'P10_ACTUAL_PRIOR_SOURCE_SENSOR_ANCHOR')
                expected = float(Fraction('42.75') * Fraction(str(anchor[2])) / Fraction(str(anchor[1])))
                need(result[SID] == expected, 'P10_ACTUAL_LEADERSHIP_CASH_SENSOR_OPERATION_ORDER')
            else:
                need(SID not in result, 'P10_UNSELECTED_SOURCE_NOT_IN_TERMINAL_SENSOR')
            frames = []
            frame = inspect.currentframe().f_back
            while frame is not None:
                frames.append((frame.f_code.co_name, frame.f_globals.get('__name__')))
                frame = frame.f_back
            need(('plan_session', 'sentinel.core.kernel') in frames, 'P10_SENSOR_ACTUAL_CANONICAL_KERNEL_CALLSITE')
            self.current['sensors'].append(dict(selected=selected, result=deepcopy(result),
                prior_anchor=deepcopy(prior.feed['series'].get(SID, {}).get('signal_basis_anchor')),
                expected_source_value=expected, canonical_kernel_callsite=True))
            self.current['order'].append('POST_PLAN_SENSOR')
        return result

    def finish(self, prior, next_run):
        from research.pooled_vacancy_funding import runtime
        record = self.current
        need(record is not None and runtime.checkpoint(prior) == record['prior'],
             'P10_EVERY_ACTUAL_CALLER_PRIOR_FULL_RUNTIME_UNCHANGED')
        record['checkpoint'] = runtime.checkpoint(next_run)
        need(digest(record['publication']) == record['publication_sha256'],
             'P10_ENTIRE_SERIALIZED_PUBLICATION_IDENTITY_NO_NUMERIC_TYPE_EXCLUSIONS')
        need(record['checkpoint']['state']['last_processed_session'] == record['session'],
             'P10_ACTUAL_NEXT_RUNTIME_SESSION')
        if record['session'] == AFFECTED and self.binding.new_input:
            need(not any(x['security_id'] == SID for x in record['publication']['bars']),
                 'P10_NO_CASH_AS_SOURCE_QUOTE_OR_FABRICATED_FEB15_BAR')
            actual = [x for x in record['terminal'] if x['actual_context_call']]
            need(len(actual) == 1 and record['engines'] and record['sensors']
                 and record['order'].index('ACTUAL_TERMINAL') < record['order'].index('ENGINE_BEGIN')
                 and not any(x['security_id'] == SID for x in record['risk']),
                 'P10_ACTUAL_TERMINAL_SETTLEMENT_PRECEDES_INTACT_SURVIVOR_RISK_LOOP')
            need(not any(x['security_id'] == SID for x in next_run.state.pending),
                 'P10_TERMINAL_SOURCE_PENDING_INTENTS_EXTINGUISHED')
        self.current = None
        if record['session'] <= AFFECTED:
            self.records.append(record)
        return record

    def refusal(self, prior, error):
        from research.pooled_vacancy_funding import runtime
        record = self.current
        need(record is not None and runtime.checkpoint(prior) == record['prior'],
             'P10_ACTUAL_FAILED_ADVANCE_CALLER_PRIOR_UNCHANGED')
        record['refused_prior_after_checkpoint'] = runtime.checkpoint(prior)
        record['refusal'] = dict(type=type(error).__name__, message=str(error), committed=False)
        self.current = None
        return record
