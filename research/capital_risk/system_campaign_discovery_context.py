"""Hosted diagnostic hooks. Never a financial settlement or account model."""
from copy import deepcopy
from dataclasses import asdict, is_dataclass, replace
from enum import Enum
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from full_system_core import hosted

TAINT = 'DISCOVERY_ONLY_NOT_FINANCIAL_AUTHORITY'
CHECKPOINT = 'research.disposable-trading-discovery-checkpoint/1'
LEADERSHIP_REFUSALS = (
    'incomplete leadership cash terminal:',
    'incomplete leadership conversion:',
    'leadership conversion lacks delivered close:',
    'unsupported leadership terminal:',
    'leadership terminal lacks prior price basis:',
)


def need(value, reason):
    if not value:
        raise ValueError(reason)


def material(value):
    if is_dataclass(value):
        return material(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Fraction):
        return dict(exact_fraction=[value.numerator, value.denominator])
    if isinstance(value, dict):
        return {str(k): material(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [material(v) for v in value]
    return value


def encoded(value):
    return json.dumps(material(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


class Event(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.disposable-trading-discovery-event/1'] = 'research.disposable-trading-discovery-event/1'
    authority: Literal['DISCOVERY_ONLY_NOT_FINANCIAL_AUTHORITY'] = TAINT
    sequence: int
    session: str
    kind: str
    security_id: str | None
    roles: list[str]
    prior_state_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    input_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    context: dict[str, Any]


def require_strict_checkpoint(value):
    """Admission guard, including explicitly tainted nested/wrapper payloads."""
    need(isinstance(value, dict), 'STRICT_CHECKPOINT_OBJECT_REQUIRED')
    need(value.get('schema') != CHECKPOINT and value.get('authority') != TAINT
         and value.get('financial_authority') is not False,
         'DISCOVERY_CHECKPOINT_CANNOT_ENTER_FINANCIAL_REPLAY')
    need(value.get('schema') == 'research.pooled-vacancy-backtest/1',
         'STRICT_FINANCIAL_OUTER_SCHEMA_REQUIRED')
    return value


def discovery_checkpoint(runtime_checkpoint, *, parent_outer_sha256, cursor, transitions, event_chain_sha256):
    """Wrap, rather than relabel, the canonical runtime's diagnostic snapshot."""
    need(type(transitions) is int and transitions >= 0, 'DISCOVERY_TRANSITION_COUNT')
    need(runtime_checkpoint['state']['last_processed_session'] == cursor,
         'DISCOVERY_RUNTIME_AND_SOURCE_CURSOR_EQUAL')
    return dict(schema=CHECKPOINT, authority=TAINT, financial_authority=False,
        strict_parent_outer_sha256=parent_outer_sha256, source_cursor=cursor,
        discovery_transitions=transitions, event_chain_sha256=event_chain_sha256,
        runtime_checkpoint=deepcopy(runtime_checkpoint), account_performance_computed=False)


def modules():
    hosted()
    from research.pooled_vacancy_funding import runtime
    from sentinel.core import kernel
    from sentinel.controller import terminal_returns, median5
    from stock_strategy_shared.wealth_core import terminal, state, marks
    return SimpleNamespace(runtime=runtime, kernel=kernel, terminal=terminal,
        terminal_returns=terminal_returns, median5=median5, state=state, marks=marks)


class DiscoveryContext:
    """Scoped approximation around the unchanged canonical Core transition."""
    def __init__(self, output, *, source_sha256, bindings=None):
        self.output = Path(output)
        self.source_sha256 = source_sha256
        self.bindings = bindings
        self.sequence = 0
        self.chain = digest(dict(authority=TAINT))
        self.current = None
        self.saved = []
        self.transitions = 0
        self.active = False
        self.tainted = False
        self.metadata_for = None
        self.metadata = None

    def patch(self, owner, name, replacement):
        original = getattr(owner, name)
        self.saved.append((owner, name, original))
        setattr(owner, name, replacement)
        return original

    def __enter__(self):
        hosted()
        need(not self.active and not self.saved, 'DISCOVERY_CONTEXT_NOT_REENTRANT')
        self.m = self.bindings if self.bindings is not None else modules()
        self.stream = (self.output/'discovery-events.jsonl').open('xb')
        try:
            self.original_apply = self.patch(self.m.terminal, 'apply_terminal', self.apply_terminal)
            self.original_orphans = self.patch(self.m.terminal, 'sweep_orphans', self.sweep_orphans)
            # Use a function descriptor: the Core state instance remains first.
            def equity(owner, marks, *, noncash_assets=0.0):
                return self.equity_view(owner, marks, noncash_assets=noncash_assets)
            self.original_equity = self.patch(self.m.state.PortfolioState, 'equity_view', equity)
            self.original_values = self.patch(self.m.terminal_returns, 'values', self.values)
            self.original_witness = self.patch(self.m.median5, 'witness', self.witness)
            self.original_plan = self.patch(self.m.kernel, 'plan_session', self.plan)
            self.original_advance = self.patch(self.m.runtime, 'advance', self.advance)
            self.active = True
            return self
        except BaseException:
            self.restore()
            self.stream.close()
            raise

    def restore(self):
        for owner, name, original in reversed(self.saved):
            setattr(owner, name, original)
        self.saved.clear()
        self.active = False

    def emit(self, kind, sid=None, *, bypass=False, **context):
        need(self.current is not None, 'DISCOVERY_EVENT_NEEDS_CURRENT_TRANSITION')
        if self.metadata_for is not self.current:
            prior = self.current[0].state
            self.metadata = dict(prior_state_sha256=prior.state_hash,
                held={v['security_id'] for v in prior.wealth_core['episodes'].values()},
                pending={v['security_id'] for v in prior.pending},
                leaders=set((prior.median5 or {}).get('selected', ())))
            self.metadata_for = self.current
        held, pending, leaders = (self.metadata[k] for k in ('held', 'pending', 'leaders'))
        roles = [label for label, names in (('HELD', held), ('PENDING', pending), ('LEADERSHIP', leaders)) if sid in names]
        if sid is not None and not roles:
            roles = ['UNHELD_UNSELECTED']
        event = Event(sequence=self.sequence, session=self.current[1].session,
            kind=kind, security_id=sid, roles=roles,
            prior_state_sha256=self.metadata['prior_state_sha256'], source_sha256=self.source_sha256,
            input_sha256=self.current[0].input_sha256,
            context=material(dict(bypass=bypass, **context))).model_dump()
        self.chain = digest(dict(previous=self.chain, event=event))
        self.stream.write(encoded(dict(event=event, chain_sha256=self.chain))+b'\n')
        self.stream.flush(); os.fsync(self.stream.fileno())
        self.sequence += 1
        self.tainted |= bypass

    def carry(self, terms, refusal):
        self.emit('TERMINAL_APPLICATION_BYPASSED', terms.security_id, bypass=True,
            source_term=terms, refusal=refusal,
            convention='KEEP_EXISTING_SHARES_CASH_AND_OCCUPIED_SLOT_NO_SETTLEMENT')
        return dict(applied=False, pending=True, security_id=terms.security_id,
            reason='DISCOVERY_UNSETTLED_TERMINAL', authority=TAINT)

    def apply_terminal(self, state, terms, **kwargs):
        shares = sum((Fraction(str(v.current_shares)) for v in state.episodes.values()
                      if v.security_id == terms.security_id), Fraction(0))
        complete, why = terms.completeness(shares)
        if not complete:
            return self.carry(terms, 'INCOMPLETE_TERMS:'+str(why))
        # A probe cannot partially change the real diagnostic book on refusal.
        copied = deepcopy(kwargs)
        probe_state = deepcopy(state)
        try:
            result = self.original_apply(probe_state, terms, **copied)
        except self.m.terminal.TermsIncomplete as exc:
            return self.carry(terms, type(exc).__name__+':'+str(exc))
        if not result.get('applied') and not result.get('converted') and result.get('reason') != 'NOT_HELD':
            return self.carry(terms, 'CANONICAL_NON_APPLICATION:'+str(result.get('reason')))
        return self.original_apply(state, terms, **kwargs)

    def sweep_orphans(self, state, **kwargs):
        for ep in state.episodes.values():
            stale = state.sessions_since_valid_mark.get(ep.security_id, 0)
            if stale:
                self.emit('ABSENT_HOLDING_RETAINED', ep.security_id, bypass=True,
                    missing_sessions=stale, shares=ep.current_shares,
                    convention='NO_ABSENCE_ONLY_ORPHAN_SETTLEMENT_OR_WRITE_OFF')
        return []

    def equity_view(self, state, marks, *, noncash_assets=0.0):
        adapted = dict(marks)
        for sid in state.shares_by_security():
            mark = adapted.get(sid)
            need(mark is not None, 'DISCOVERY_HELD_MARK_STATUS_REQUIRED')
            if mark.resolves_equity:
                continue
            need(positive(mark.stale_raw_close), 'DISCOVERY_NO_POSITIVE_PRIOR_MARK:'+sid)
            self.emit('DIAGNOSTIC_SIZING_CARRY', sid, bypass=True,
                original_status=mark.status.value, source_stale_raw_close=mark.stale_raw_close,
                source_print_session=state.last_valid_mark_session.get(sid),
                convention='EPHEMERAL_VALUATION_ONLY_NO_BAR_NO_OPEN_NO_FILL_NO_SETTLEMENT')
            adapted[sid] = replace(mark, status=self.m.marks.MarkStatus.PENDING_TERMS_CARRIED,
                                  carried_raw_close=mark.stale_raw_close)
        return self.original_equity(state, adapted, noncash_assets=noncash_assets)

    def values(self, *, prior, published):
        values = {}
        for terms in published.terminal_events:
            packet = replace(published, terminal_events=(terms,))
            try:
                found = self.original_values(prior=prior, published=packet)
            except ValueError as exc:
                if not str(exc).startswith(LEADERSHIP_REFUSALS):
                    raise
                self.emit('LEADERSHIP_TERMINAL_REFUSAL', terms.security_id, bypass=True,
                    source_term=terms, refusal=str(exc), convention='NO_SYNTHETIC_TERMINAL_VALUE')
                continue
            need(not set(values).intersection(found), 'DISCOVERY_DUPLICATE_LEADERSHIP_TERMINAL')
            values.update(found)
        return values

    def witness(self, state, **kwargs):
        selected = []
        terminal = kwargs.get('terminal_values') or {}
        for sid in state['selected']:
            before = state['selected_closes'].get(sid)
            now = terminal[sid] if sid in terminal else kwargs['closes'].get(sid)
            valid_now = (type(now) in (int, float) and math.isfinite(now)
                         and (now >= 0 if sid in terminal else now > 0))
            if positive(before) and valid_now:
                selected.append(sid)
            else:
                self.emit('UNOBSERVABLE_WITNESS_RETURN_OMITTED', sid, bypass=True,
                    prior_signal_close=before, observed_signal_close=now,
                    convention='ORIGINAL_WITNESS_ON_OBSERVABLE_SUBSET_NO_ASSUMED_ZERO_RETURN')
        detached = deepcopy(state)
        detached['selected'] = selected
        detached['selected_closes'] = {sid: state['selected_closes'][sid] for sid in selected}
        if selected != state['selected']:
            self.emit('DIAGNOSTIC_WITNESS_DENOMINATOR', bypass=True,
                prior_members=len(state['selected']), observed_members=len(selected),
                empty_subset_convention='CANONICAL_EMPTY_WITNESS_CHANGE_ZERO')
        return self.original_witness(detached, **kwargs)

    def plan(self, **kwargs):
        result = self.original_plan(**kwargs)
        candidates = {v.security_id for v in result.leadership_candidates}
        for terms in self.current[1].terminal_events:
            self.emit('TERMINAL_CANDIDATE_MEMBERSHIP', terms.security_id,
                candidate=terms.security_id in candidates)
        return result

    def advance(self, run, published):
        need(self.current is None, 'DISCOVERY_TRANSITION_NOT_REENTRANT')
        self.current = (run, published)
        prior_hash = run.state.state_hash
        publication_hash = digest(published)
        try:
            for terms in published.terminal_events:
                self.emit('SOURCE_TERMINAL_OBSERVED', terms.security_id, source_term=terms)
            result = self.original_advance(run, published)
            before = run.state.ledger['events']
            after = result.state.ledger['events']
            need(after[:len(before)] == before, 'DISCOVERY_CANONICAL_LEDGER_PREFIX_UNCHANGED')
            need(run.state.state_hash == prior_hash and digest(published) == publication_hash,
                 'DISCOVERY_PRIOR_AND_PUBLICATION_UNCHANGED')
            self.emit('CORE_TRANSITION_COMMITTED', next_state_sha256=result.state.state_hash,
                publication_sha256=publication_hash, new_ledger_events=after[len(before):],
                pending_after=result.state.pending, decision=result.state.last_decision,
                path_has_bypasses=self.tainted, account_performance_computed=False)
            self.transitions += 1
            return result
        except BaseException as exc:
            self.emit('DISCOVERY_TRANSITION_REFUSED', refusal=type(exc).__name__+':'+str(exc),
                transition_committed=False)
            raise
        finally:
            self.current = None

    def __exit__(self, *args):
        self.restore()
        self.stream.close()
