"""Pure compound-input scaffold; hosted integration/retention is deliberately separate.

This module changes input event representation only. It cannot advance a session,
restore or serialize a financial book, or activate itself on a runner.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from system_campaign_distribution_facts import compile_spin_function
from system_campaign_financial_distribution_source_v1 import digest, need

MODEL = 'research.daily-compound-distribution-terminal-assumption/1'
PROJECTION = 'research.qualified-distribution-session-projection/1'
REPAIR_SHA = '1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152'


class CompoundAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.daily-compound-distribution-terminal-assumption/1'] = Field(alias='schema')
    actual_distribution_session: str
    actual_merger_session: str
    recognition_session: str
    cash_election_assumed: Literal[True]
    actual_election_claimed: Literal[False]
    original_carried_unit: Literal['PRE_DISTRIBUTION_PARENT_SHARE']
    remaining_parent_fraction: str
    cash_per_remaining_parent_share: str
    delivered_ratio_per_remaining_parent_share: str
    cash_per_original_carried_share: str
    delivered_ratio_per_original_carried_share: str
    distributed_child_ratio_per_original_carried_share: str
    opening_availability_assumed: Literal[True]
    actual_settlement_claimed: Literal[False]
    fractional_cash_proxy: Literal['FROZEN_DELIVERED_RAW_OPEN_NOT_ACTUAL_SETTLEMENT_RATE']
    settlement_fees: Literal['IGNORED_FOR_RESEARCH']
    continuing_delivered_whole_shares_supported: Literal[False]


def validate_model(value):
    model = CompoundAssumption.model_validate(value)
    remaining = Fraction(model.remaining_parent_fraction)
    cash = Fraction(model.cash_per_remaining_parent_share)
    ratio = Fraction(model.delivered_ratio_per_remaining_parent_share)
    child = Fraction(model.distributed_child_ratio_per_original_carried_share)
    need(0 < remaining < 1 and cash > 0 and ratio > 0 and child > 0
         and model.actual_distribution_session < model.actual_merger_session == model.recognition_session
         and remaining * cash == Fraction(model.cash_per_original_carried_share)
         and remaining * ratio == Fraction(model.delivered_ratio_per_original_carried_share),
         'COMPOUND_EXACT_ORIGINAL_UNIT_CONSIDERATION')
    return model


def literal_number(literal):
    value = float(literal)
    need(Fraction(str(value)) == Fraction(literal) and value > 0,
         'COMPOUND_NO_FLOAT_LITERAL_RATIO_OR_CASH_DRIFT')
    return value


def build_terms(model_value, witness, *, child_security_id, delivered_security_id, reference):
    """Construct data only after source DATA admission is supplied by the caller."""
    model = validate_model(model_value)
    need(witness['schema'] == 'research.own-parent-frozen-source-witnesses/6'
         and witness['financial_authority'] is witness['input_adopted'] is False
         and witness['financial_sessions_advanced'] == 0
         and witness['parent_cursor'] < model.actual_distribution_session,
         'COMPOUND_SOURCE_ONLY_WITNESS_AND_UNCONSUMED_ROOT')
    term, = witness['terms']; native, = witness['native_distributions']
    parent = term['source_row']['security_id']
    rows = {v['source_row']['security_id']: v['source_row'] for v in witness['additional_rows']}
    need(len(rows) == 3 and set(rows) == {parent, child_security_id, delivered_security_id}
         and len({parent, child_security_id, delivered_security_id}) == 3
         and all(r['session'] == model.recognition_session for r in rows.values())
         and native['native_distribution']['parent_security_id'] == parent
         and native['native_distribution']['session'] > model.recognition_session == term['native_term']['session'],
         'COMPOUND_EXACT_THREE_RECOGNITION_ROWS_AND_TWO_NATIVE_DATES')
    held = term['parent_positions']
    need(len(held) == 1 and held[0]['quantity'] > 0
         and next(v['parent_positions'] for v in witness['additional_rows'] if v['source_row']['security_id'] == parent) == held
         and all(not v['parent_positions'] for v in witness['additional_rows'] if v['source_row']['security_id'] != parent),
         'COMPOUND_EXACT_HELD_PARENT_AND_UNHELD_CHILDREN')
    entitlement = Fraction(str(held[0]['quantity'])) * Fraction(model.delivered_ratio_per_original_carried_share)
    need(entitlement > 0 and entitlement.numerator // entitlement.denominator == 0,
         'COMPOUND_NO_UNQUALIFIED_CONTINUING_DELIVERED_EPISODE')
    child, delivered = rows[child_security_id], rows[delivered_security_id]
    need(all(r['tradeable'] == '1' and Fraction(r['raw_open']) > 0 for r in (child, delivered))
         and Fraction(rows[parent]['dividend_per_share']) == 0,
         'COMPOUND_EXACT_TRADEABLE_OPEN_AND_ZERO_EXISTING_CASH_PROXY')
    spin = dict(session=model.recognition_session, parent_ticker=term['source_row']['ticker'], parent_security_id=parent,
        child_ticker=child['ticker'], child_security_id=child_security_id,
        source_row_id=native['native_distribution']['source_row_id'], value_evidence=reference,
        child_shares_per_parent=model.distributed_child_ratio_per_original_carried_share,
        child_price=None, cash_in_lieu_price=str(float(child['raw_open'])), policy='LIQUIDATE_CHILD_AT_OPEN')
    added = dict(session=model.recognition_session, security_id=parent, kind='CASH_PLUS_STOCK', reference=reference,
        cash_per_share=literal_number(model.cash_per_original_carried_share), delivered_security_id=delivered_security_id,
        delivered_ticker=delivered['ticker'], delivered_issuer_id=delivered['issuer_id'],
        exchange_ratio=literal_number(model.delivered_ratio_per_original_carried_share),
        cash_in_lieu_price_per_delivered_share=float(delivered['raw_open']), entitlement_aggregation='HOLDER')
    return dict(research_assumption=deepcopy(model_value), source_witness_sha256=digest(witness),
        original_native_distribution=deepcopy(native['native_distribution']),
        original_native_distribution_sha256=native['native_distribution_sha256'],
        original_terminal=deepcopy(term['native_term']), parent_positions=deepcopy(held),
        parent_outer_sha256=witness['parent_outer_sha256'], parent_cursor=witness['parent_cursor'],
        spin=spin, terminal=added, original_rows=deepcopy(rows))


def actual_role(state, pending, binding):
    """Exact held-parent role before original canonical distribution/terminal calls."""
    parent = binding['spin']['parent_security_id']
    child = binding['spin']['child_security_id']
    delivered = binding['terminal']['delivered_security_id']
    wanted = {parent, child, delivered}
    episodes = state['wealth_core']['episodes'] if 'wealth_core' in state else state['episodes']
    held = [dict(slot_id=e['slot_id'], ticker=e['ticker'], quantity=e['current_shares'], entry_date=e['entry_date'])
        for _, e in sorted(episodes.items(), key=lambda pair: int(pair[0])) if e['security_id'] == parent]
    def contains_identity(value):
        if isinstance(value,dict):
            fields=('security_id','reserved_for','delivered_security_id','parent_security_id','child_security_id')
            if any(k in fields and isinstance(v,str) and v in wanted for k,v in value.items()):
                return True
            return any(contains_identity(v) for v in value.values())
        return isinstance(value,(tuple,list)) and any(contains_identity(v) for v in value)
    need(held == binding['parent_positions'] and all(e['security_id'] not in (child, delivered) for e in episodes.values())
         and not any(contains_identity(order) for order in pending),
         'COMPOUND_ACTUAL_EXACT_PARENT_ROLE_NO_CHILD_OR_ORDER')
    core = state.get('wealth_core', state)
    need(not any(slot.get('reserved_for') in wanted for slot in core['slots'].values())
         and all(not any(sid in core.get(name, {}) for sid in wanted)
                 for name in ('terminal_pending_terms', 'terminal_pending_sessions', 'unresolved_terminals')),
         'COMPOUND_ACTUAL_NO_UNQUALIFIED_RESERVATION_OR_CLAIM')
    need(not contains_identity(state.get('ledger',{}).get('receivables',[])),
         'COMPOUND_ACTUAL_NO_UNQUALIFIED_RECEIVABLE')
    return True


class EventSessionProjection:
    """Scoped input-only projection, delegating the unchanged original pure codec.

    The caller must supply a qualified retained activation, canonical factories
    and the ordinary terminal overlay applied BEFORE this input transformation.
    No engine hooks or monkeypatches are installed by this scaffold.
    """
    def __init__(self, binding, *, parent_bar, child_bar, source_raw, source_namespace, spin_factory):
        self.binding = deepcopy(binding)
        validate_model(binding['research_assumption'])
        need(digest(binding['original_native_distribution']) == binding['original_native_distribution_sha256'],
             'COMPOUND_ORIGINAL_DISTRIBUTION_IMMUTABLE')
        self.original = spin_factory(**binding['original_native_distribution'])
        self.added = spin_factory(**binding['spin'])
        self.projected = replace(self.original, session=binding['spin']['session'])
        need(parent_bar.security_id == binding['spin']['parent_security_id']
             and child_bar.security_id == binding['spin']['child_security_id']
             and parent_bar.session == child_bar.session == binding['spin']['session']
             and Fraction(str(parent_bar.dividend_per_share)) == 0
             and Fraction(str(child_bar.raw_open)) == Fraction(binding['spin']['cash_in_lieu_price']),
             'COMPOUND_EXACT_SOURCE_OPENING_BARS')
        self.parent_bar_sha256 = digest(asdict(parent_bar));self.child_bar_sha256 = digest(asdict(child_bar))
        self.fn = compile_spin_function(source_raw, source_namespace, {
            '224580439420294771':binding['spin']['parent_security_id'],
            '37439132904117100':binding['spin']['child_security_id'],
            'GE':binding['spin']['parent_ticker'],'GEV':binding['spin']['child_ticker']})
        self.local = SimpleNamespace(_resume_session=binding['parent_cursor'], earliest_affected_session=binding['spin']['session'],
            suppress=(SimpleNamespace(term_sha256=digest(asdict(self.projected))),),
            add=(SimpleNamespace(cash_in_lieu_price=binding['spin']['cash_in_lieu_price'],terms=lambda:self.added),),
            parent_bar_sha256=self.parent_bar_sha256, child_bar_sha256=self.child_bar_sha256, cash_proxy_per_parent='0.0')
        self.descriptor = dict(schema=PROJECTION, parent_outer_sha256=binding['parent_outer_sha256'],
            parent_cursor=binding['parent_cursor'], compound_input_sha256=digest(binding), original_repair_sha256=REPAIR_SHA,
            original_native_sha256=digest(asdict(self.original)), projected_native_sha256=digest(asdict(self.projected)),
            added_spin_sha256=digest(asdict(self.added)), recognition_session=binding['spin']['session'],
            parent_bar_sha256=self.parent_bar_sha256, child_bar_sha256=self.child_bar_sha256)
        self.activation_sha256 = digest(self.descriptor)

    def _bound(self, activation):
        need(digest(self.binding) == self.descriptor['compound_input_sha256']
             and digest(self.descriptor) == self.activation_sha256 and activation == self.descriptor
             and digest(asdict(self.original)) == self.descriptor['original_native_sha256']
             and digest(asdict(self.added)) == self.descriptor['added_spin_sha256']
             and digest(asdict(self.projected)) == self.descriptor['projected_native_sha256']
             and self.local._resume_session == self.descriptor['parent_cursor']
             and self.local.earliest_affected_session == self.descriptor['recognition_session']
             and self.local.cash_proxy_per_parent == '0.0'
             and self.local.parent_bar_sha256 == self.descriptor['parent_bar_sha256']
             and self.local.child_bar_sha256 == self.descriptor['child_bar_sha256']
             and [s.term_sha256 for s in self.local.suppress] == [self.descriptor['projected_native_sha256']]
             and self.local.add[0].terms() == self.added,
             'COMPOUND_EXACT_IMMUTABLE_QUALIFIED_ACTIVATION')

    def apply(self, packet, activation):
        self._bound(activation)
        before = digest(asdict(packet))
        origin = self.original
        targets = [v for v in packet.spins if v.source_row_id == origin.source_row_id]
        if packet.day == origin.session:
            need(len(targets) == 1 and digest(asdict(targets[0])) == digest(asdict(origin)),
                 'COMPOUND_EXACT_ORIGINAL_SOURCE_DATE_SUPPRESSION')
            changed = replace(packet, spins=tuple(v for v in packet.spins if v.source_row_id != origin.source_row_id))
        elif packet.day == self.added.session:
            need(not targets and not any(v.parent_security_id == origin.parent_security_id for v in packet.spins),
                 'COMPOUND_NO_DUPLICATE_RECOGNITION_DATE_DISTRIBUTION')
            terminal = [v for v in packet.terminal if v.security_id == origin.parent_security_id]
            need(len(terminal) == 1 and digest(asdict(terminal[0])) == digest(self.binding['terminal']),
                 'COMPOUND_ORDINARY_COMPLETE_TERMINAL_MUST_ALREADY_BE_PRESENT')
            projected = replace(packet, spins=tuple(packet.spins) + (self.projected,))
            changed = self.fn(projected, self.local)
            need(changed.terminal == packet.terminal and changed.bars == packet.bars
                 and tuple(changed.spins) == tuple(packet.spins) + (self.added,),
                 'COMPOUND_ONLY_QUALIFIED_SPIN_CHANGED_NO_FABRICATED_BARS')
        else:
            need(not targets, 'COMPOUND_SOURCE_EVENT_CANNOT_APPEAR_ON_ANOTHER_DATE')
            changed = packet
        need(digest(asdict(packet)) == before, 'COMPOUND_ORIGINAL_PACKET_UNCHANGED')
        return changed
