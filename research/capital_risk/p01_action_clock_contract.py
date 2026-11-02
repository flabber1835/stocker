"""Pure source-bound clock proposal and packet transform; no financial imports."""
from dataclasses import fields, replace
from typing import Literal

from pydantic import BaseModel, ConfigDict

from system_campaign_discovery_context import digest, material
from full_system_benchmark import need

SID = '718647188059134933'
OLD = '2019-09-30'
NEW = '2019-10-01'
AUTHORITY = 'QUALIFICATION_ONLY_NOT_FINANCIAL_AUTHORITY'


class NativeTerm(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    session: Literal['2019-09-30'] = OLD
    security_id: Literal['718647188059134933'] = SID
    kind: Literal['CASH_MERGER'] = 'CASH_MERGER'
    cash_per_share: None = None
    delivered_security_id: None = None
    delivered_ticker: None = None
    delivered_issuer_id: None = None
    exchange_ratio: None = None
    cash_in_lieu_price_per_delivered_share: None = None
    reference: Literal['actions/delisted'] = 'actions/delisted'
    entitlement_aggregation: Literal['HOLDER'] = 'HOLDER'


class Proposal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.p01-action-clock-proposal/1'] = 'research.p01-action-clock-proposal/1'
    authority: Literal['QUALIFICATION_ONLY_NOT_FINANCIAL_AUTHORITY'] = AUTHORITY
    parent_outer: Literal['c98df4b3c919f725162b86e1c98d67b0f710805774c4c2a37fa4755f55738034']
    parent_inner: Literal['64f4d7d71cfc70f9a8be6d986f9937a76a5845fde93e46bc81e855372b9c24df']
    parent_state: Literal['f86859a6b0f02bc16f303c705d6ee56c8e0cb80122f313a1c94392366131dee3']
    parent_input: Literal['2ce8b81eb52c779f9bd47f5e81c5c9c2445f3e8714b2c6a1469aac2d456fab81']
    source_binding: Literal['cbff432d861381735e7bba6ecd79491b059405cde8840cc2d128dbbad85d0b14']
    old_session: Literal['2019-09-30'] = OLD
    candidate_session: Literal['2019-10-01'] = NEW
    native: NativeTerm
    legal_settlement_day_proved: Literal[True] = True
    exact_exchange_last_trade_notice_admitted: Literal[False] = False
    financial_input_admitted: Literal[False] = False


def proposal(spec):
    return Proposal(parent_outer=spec['outer_sha256'], parent_inner=spec['inner_sha256'],
        parent_state=spec['state_sha256'], parent_input=spec['input_sha256'],
        source_binding=spec['source_binding_sha256'], native=NativeTerm())


def check_native(term, expected):
    need(material(term) == expected.model_dump(), 'P01_CLOCK_EXACT_NATIVE_TERM_PREIMAGE')


def unchanged_payload(original, changed):
    need(type(original) is type(changed), 'P01_CLOCK_EXACT_PACKET_TYPE')
    need(all(getattr(original, f.name) is getattr(changed, f.name)
             for f in fields(original) if f.name != 'terminal'),
         'P01_CLOCK_ONLY_TERMINAL_FIELD_REPLACED')


class Clock:
    """One exact remove/reinsert pair. Never substitutes economic terms."""
    def __init__(self, contract):
        self.contract = Proposal.model_validate(contract)
        self.original = None
        self.sessions = []

    def apply(self, packet):
        need(self.sessions in ([], [OLD]), 'P01_CLOCK_BOUNDED_TWO_SESSION_SEQUENCE')
        expected = OLD if not self.sessions else NEW
        need(packet.day == expected, 'P01_CLOCK_EXACT_ORDERED_SOURCE_DAY')
        matches = [t for t in packet.terminal if t.security_id == SID]
        if expected == OLD:
            need(len(matches) == 1, 'P01_CLOCK_ONE_ORIGINAL_TERM')
            check_native(matches[0], self.contract.native)
            self.original = matches[0]
            terms = tuple(t for t in packet.terminal if t is not self.original)
        else:
            need(self.original is not None and not matches, 'P01_CLOCK_NO_DUPLICATE_CANDIDATE_TERM')
            check_native(self.original, self.contract.native)
            moved = replace(self.original, session=NEW)
            need(material(moved) == {**self.contract.native.model_dump(), 'session': NEW},
                 'P01_CLOCK_SESSION_ONLY_TERM_CHANGE')
            terms = (*packet.terminal, moved)
        changed = replace(packet, terminal=terms)
        unchanged_payload(packet, changed)
        self.sessions.append(expected)
        return changed

    def proof(self):
        return dict(authority=AUTHORITY, financial_authority=False, sessions=list(self.sessions),
            native_term_sha256=digest(self.contract.native.model_dump()),
            exact_original_incomplete_term_carried=self.sessions == [OLD, NEW],
            quotes_windows_cash_spinoffs_changed=False, settlement_terms_supplied=False,
            exact_exchange_last_trade_notice_admitted=False)
