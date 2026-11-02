"""Exact source-term/date codec for one own-bound batch; no price aliases."""
from collections import Counter
from dataclasses import fields,replace
import json
from pathlib import Path

from p01_factual_batch_contract import (BatchInput,SCHEMA,document,parse,facts,term,need,digest)
from system_campaign_discovery_context import material


def source_terms():
    from full_system_core import hosted
    hosted()
    from research.pooled_input_support.inputs import load_actions
    actions=load_actions(Path('/frozen/bundle'))
    return {day:tuple(values) for day,values in actions.terminal.items()}


class InputCodec:
    def __init__(self,native):
        self.native=native;self.expected=document();self.records=self.expected['actions'];self.objects=[]
        self.applied=[];self.control_applications=[];self.control=False
        for a in self.records:
            for n in a['native_events']:
                matches=[t for t in native.get(n['session'],()) if t.security_id==a['source_security_id']
                         and digest(material(t))==n['sha256']]
                need(len(matches)==1,'EXACT_FROZEN_NATIVE_PREIMAGE:'+a['action_id'])

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        if json.loads(Path(path).read_bytes()).get('schema')!=SCHEMA:
            return self.original_load(path,resume_session=resume_session,
                predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        obj=parse(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        self.objects.append(obj);return obj

    def apply(self,packet,loaded):
        if not isinstance(loaded,BatchInput):return self.original_apply(packet,loaded)
        need(any(loaded is x for x in self.objects) and loaded.model_dump(by_alias=True)==self.expected,
             'ONLY_EXACT_REGISTERED_ELEVENTH_OBJECT')
        terms=packet.terminal;changed_ids=[]
        for a in self.records:
            expected=[n['sha256'] for n in a['native_events'] if n['session']==packet.day]
            effective=a['economic_session']==packet.day
            if not expected and not effective:continue
            matches=[t for t in terms if t.security_id==a['source_security_id']]
            need(Counter(digest(material(t)) for t in matches)==Counter(expected),
                 'EXACT_DATED_NATIVE_PREIMAGE_OR_NO_TARGET_COLLISION:'+a['action_id'])
            terms=tuple(t for t in terms if not any(t is x for x in matches))
            if effective:
                from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict
                value=terminal_terms_from_dict(term(a))
                need(material(value)==term(a) and value.completeness(0)[0],
                     'COMPLETE_ORDINARY_LEGAL_TERM_NO_DEFAULT_CIL:'+a['action_id'])
                terms=(*terms,value)
            changed_ids.append(dict(action_id=a['action_id'],session=packet.day,
                exact_native_entries_removed=len(expected),complete_economic_entry_inserted=effective))
        if not changed_ids:return packet
        changed=replace(packet,terminal=terms)
        need(all(getattr(packet,f.name) is getattr(changed,f.name) for f in fields(packet) if f.name!='terminal'),
             'ONLY_TERMINAL_PACKET_FIELD_CAN_CHANGE')
        (self.control_applications if self.control else self.applied).extend(changed_ids)
        return changed

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
