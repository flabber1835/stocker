"""Typed CELG market-boundary input; no ordinary repair or synthetic quote alias."""
from copy import deepcopy
from dataclasses import fields,replace
from datetime import date
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,PrivateAttr
from p01_celg_bridge_gate import PARENT,INNER,STATE,INPUT,need,digest

SCHEMA='research.p01-celg-market-clock-input/1'
SID='11651249425833422';BMY='578964201416671255'
OLD='2019-11-20';NEW='2019-11-21'
NATIVE=dict(session=OLD,security_id=SID,kind='CASH_MERGER',cash_per_share=None,
    delivered_security_id=None,delivered_ticker=None,delivered_issuer_id=None,exchange_ratio=None,
    cash_in_lieu_price_per_delivered_share=None,reference='actions/acquisitionby deal_value_musd=77036',
    entitlement_aggregation='HOLDER')
NATIVE_SHA='dd6dfe47583ae98783a1d88a7b50912d488d0f90bc958beec02ad4b0dab667ec'
SCOPES=json.loads((Path(__file__).with_name('p01_celg_bridge_facts.json')).read_bytes())['inherited_native_scope_guards']


def unique(pairs):
    out={}
    for k,v in pairs:
        need(k not in out,'NO_DUPLICATE_INPUT_JSON_KEYS');out[k]=v
    return out


class ClockInput(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    schema_id:Literal['research.p01-celg-market-clock-input/1']=Field(alias='schema')
    original_financial_authority:dict
    source_successor_receipt_sha256:str
    source_successor_map_sha256:str
    predecessor_checkpoint_sha256:str
    predecessor_input_sha256:str
    predecessor_state_sha256:str
    native:dict
    native_term_sha256:Literal[NATIVE_SHA]
    legal_completion_day:Literal['2019-11-20']
    last_source_market_session:Literal['2019-11-20']
    economic_market_session:Literal['2019-11-21']
    treatment:Literal['COMPLETE_THREE_LEG_PACKAGE_AT_FIRST_DELIVERED_MARKET_OPEN_PRESERVE_SOURCE_CLOSE']
    quote_capsule:dict
    quote_input_sha256:str
    terms:dict
    source_evidence:dict
    pending_scope:Literal['REFUSE_UNSUPPORTED_SOURCE_OR_DELIVERED_PENDING_BEFORE_SETTLEMENT']
    _sha256:str|None=PrivateAttr(default=None)

    @property
    def earliest_affected_session(self):return OLD
    @property
    def sha256(self):return self._sha256


def document(source_checkpoint,receipt_sha256,source_map,quote,descriptor,terms,source_evidence):
    need(source_checkpoint['source_cursor']=='2019-11-19' and source_checkpoint['completed']==475,
         'INPUT_ONLY_AFTER_ZERO_SESSION_SOURCE_BOUNDARY')
    return dict(schema=SCHEMA,original_financial_authority=dict(outer_sha256=PARENT,inner_sha256=INNER,
        state_sha256=STATE,input_sha256=INPUT),source_successor_receipt_sha256=receipt_sha256,
        source_successor_map_sha256=digest(source_map),
        predecessor_checkpoint_sha256=source_checkpoint['run']['checkpoint_sha256'],
        predecessor_input_sha256=source_checkpoint['run']['input_sha256'],
        predecessor_state_sha256=source_checkpoint['run']['state_sha256'],
        native=deepcopy(NATIVE),native_term_sha256=NATIVE_SHA,
        legal_completion_day=OLD,last_source_market_session=OLD,economic_market_session=NEW,
        treatment='COMPLETE_THREE_LEG_PACKAGE_AT_FIRST_DELIVERED_MARKET_OPEN_PRESERVE_SOURCE_CLOSE',
        quote_capsule=deepcopy(descriptor),quote_input_sha256=digest(quote),terms=deepcopy(terms),
        source_evidence=deepcopy(source_evidence),
        pending_scope='REFUSE_UNSUPPORTED_SOURCE_OR_DELIVERED_PENDING_BEFORE_SETTLEMENT')


class InputCodec:
    def __init__(self,native,expected):
        from system_campaign_discovery_context import material
        need(material(native)==NATIVE and digest(NATIVE)==NATIVE_SHA,'EXACT_ACTUAL_CELG_NATIVE_PREIMAGE')
        self.native=native;self.expected=deepcopy(expected);self.objects=[];self.applied={OLD:0,NEW:0}
        ClockInput.model_validate(expected)

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        raw=Path(path).read_bytes();value=json.loads(raw,object_pairs_hook=unique)
        if value.get('schema')!=SCHEMA:
            return self.original_load(path,resume_session=resume_session,
                predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        need(len(raw)<=128*1024 and value==self.expected and resume_session=='2019-11-19'
             and predecessor_checkpoint_sha256==self.expected['predecessor_checkpoint_sha256'],
             'EXACT_SOURCE_BOUNDARY_TENTH_INPUT_AND_AUTHENTICATED_QUOTE')
        obj=ClockInput.model_validate(value);obj._sha256=hashlib.sha256(raw).hexdigest()
        self.objects.append(obj);return obj

    def apply(self,packet,loaded):
        if not isinstance(loaded,ClockInput):return self.original_apply(packet,loaded)
        need(any(loaded is x for x in self.objects)
             and loaded.model_dump(by_alias=True)==self.expected,'ONLY_UNCHANGED_REGISTERED_TENTH_INPUT')
        if packet.day not in (OLD,NEW):return packet
        from system_campaign_discovery_context import material
        matching=[t for t in packet.terminal if t.security_id==SID]
        if packet.day==OLD:
            need(len(matching)==1 and material(matching[0])==NATIVE,'EXACT_NOV20_NATIVE_TERM_NOT_SKIPPED')
            terms=tuple(t for t in packet.terminal if t is not matching[0])
        else:
            need(not matching,'NO_NOV21_SOURCE_EVENT_COLLISION')
            from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict
            term=terminal_terms_from_dict(deepcopy(loaded.terms))
            need(material(term)==loaded.terms and term.session==NEW,'COMPLETE_TYPED_RIGHT_TERM_REINSERTED')
            terms=(*packet.terminal,term)
        changed=replace(packet,terminal=terms)
        need(all(getattr(packet,f.name) is getattr(changed,f.name) for f in fields(packet) if f.name!='terminal'),
             'ONLY_EXACT_TERMINAL_PACKET_FIELD_CHANGED')
        self.applied[packet.day]+=1;return changed

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest,repair
        self.backtest,self.repair=backtest,repair
        self.original_load,self.saved_load=repair.load_repair,backtest.load_repair
        self.original_apply=backtest.apply_repair
        repair.load_repair=backtest.load_repair=self.load;backtest.apply_repair=self.apply
        return self

    def __exit__(self,*args):
        self.repair.load_repair=self.original_load;self.backtest.load_repair=self.saved_load
        self.backtest.apply_repair=self.original_apply


def roles(state):
    need(type(state.wealth_core) is dict and type(state.wealth_core.get('episodes')) is dict
         and isinstance(state.pending,(list,tuple)) and type(state.median5) is dict,
         'ACTUAL_FULL_SESSIONSTATE_ROLE_SCHEMA')
    need(all(type(p) is dict and type(p.get('security_id')) is str for p in state.pending),
         'FULL_PENDING_IDENTITY_SCHEMA')
    return dict(episodes=deepcopy(state.wealth_core['episodes']),pending=deepcopy(state.pending),
                selected=deepcopy(state.median5['selected']))


def pending_before(state):
    value=roles(state)
    need(not any(p['security_id'] in (SID,BMY) for p in value['pending']),
         'UNSUPPORTED_SOURCE_OR_DELIVERED_PENDING_REFUSES_BEFORE_COMMIT')
    return value


class RoleGuard:
    def __init__(self,quote,qualified=None,book=None):
        self.quote=quote;self.qualified=qualified;self.observed=[];self.book=book;self.scope_observed=[]

    def scope_guard(self,run,published,scope):
        role=roles(run.state);sid=scope['security_id'];day=scope['session']
        from system_campaign_discovery_context import material
        terms=[t for t in published.terminal_events if t.security_id==sid]
        need(len(terms)==1 and material(terms[0])==scope['native_term']
             and digest(material(terms[0]))==scope['native_term_sha256'],
             'EXACT_NATIVE_UNHELD_LEADERSHIP_SOURCE_TERM_AND_CLOCK')
        unsupported=any(ep['security_id']==sid for ep in role['episodes'].values()) or any(
            p['security_id']==sid for p in role['pending'])
        if unsupported:
            from research.pooled_vacancy_funding import journal
            need(self.book is not None,'NATIVE_SCOPE_ACTUAL_PRE_EVENT_BOOK_REQUIRED')
            paths=list((Path(self.book)/'pre-event').glob(day+'-*.json.gz'))
            values=[journal.read_checkpoint(p) for p in paths]
            exact=[v for v in values if v['run']==self.runtime.checkpoint(run)]
            need(len(exact)==1 and exact[0]['source_cursor']==scope['prior_session']
                 and exact[0]['sha256']==digest({k:v for k,v in exact[0].items() if k!='sha256'}),
                 'NATIVE_SCOPE_CANONICAL_PRE_EVENT_FULL_PRIOR_CHECKPOINT_MUST_ALREADY_EXIST')
            restored=self.runtime.restore(exact[0]['run'],policy=run.policy,input_sha256=run.input_sha256)
            need(self.runtime.checkpoint(restored)==exact[0]['run'],
                 'NATIVE_SCOPE_ACTUAL_PRE_EVENT_CHECKPOINT_CANONICAL_RESTORE')
            need(False,'NATIVE_UNHELD_LEADERSHIP_PROXY_CANNOT_BROADEN_TO_HELD_OR_PENDING')
        self.scope_observed.append(dict(session=day,security_id=sid,source_term_sha256=scope['native_term_sha256'],
            scope_record_sha256=scope['scope_record_sha256'],unheld=True,all_pending_absent=True))

    def advance(self,run,published):
        day=published.session
        for scope in SCOPES:
            if day==scope['session']:self.scope_guard(run,published,scope)
        if day not in (OLD,NEW):return self.original(run,published)
        before=pending_before(run.state)
        if day==OLD:
            need(all(t.security_id!=SID for t in published.terminal_events),
                 'NO_NOV21_RIGHT_OR_TERM_IN_NOV20_PUBLICATION')
        following=self.original(run,published);after=roles(following.state)
        if day==OLD:pending_before(following.state)
        else:
            need(not any(ep['security_id']==SID for ep in after['episodes'].values())
                 and not any(p['security_id']==SID for p in after['pending']),
                 'NO_OBSOLETE_SOURCE_EPISODE_OR_PENDING_AFTER_SETTLEMENT')
            from p01_celg_bridge_accounting import right_flow
            proof=right_flow(following.state.ledger['events'],self.quote)
            held=sum((Fraction(str(ep['current_shares'])) for ep in before['episodes'].values()
                      if ep['security_id']==SID),Fraction())
            need((held==0 and proof is None) or (proof is not None and proof['units']==str(int(held))
                 and held==int(held)),'ACTUAL_HELD_ENTITLEMENT_CANNOT_OMIT_RIGHTS')
        checkpoint=self.runtime.checkpoint(following)
        restored=self.runtime.restore(checkpoint,policy=following.policy,input_sha256=following.input_sha256)
        need(self.runtime.checkpoint(restored)==checkpoint,'FULL_NEW_SESSIONSTATE_PENDING_LEDGER_CANONICAL_ROUNDTRIP')
        row=dict(session=day,prior_state_sha256=run.state.state_hash,state_sha256=following.state.state_hash,
                 before=before,after=after)
        if self.qualified is not None:
            need(row==self.qualified[len(self.observed)],'FRESH_FINANCE_EXACT_QUALIFIED_FULL_STATE_AND_ROLES')
        self.observed.append(row);return following

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import runtime
        self.runtime=runtime;self.original=runtime.advance;runtime.advance=self.advance;return self

    def __exit__(self,*args):self.runtime.advance=self.original
