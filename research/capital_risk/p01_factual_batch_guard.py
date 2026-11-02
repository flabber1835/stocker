"""Actual per-use roles and durable canonical pre-event checkpoints."""
from copy import deepcopy
from fractions import Fraction
import json
import math
from pathlib import Path
import re

from p01_factual_batch_contract import facts,need,digest,sha,term
from system_campaign_discovery_context import material


def roles(state):
    need(type(state.wealth_core) is dict and type(state.wealth_core.get('episodes')) is dict
         and isinstance(state.pending,list) and type(state.median5) is dict,
         'FULL_ACTUAL_SESSIONSTATE_ROLE_SCHEMA')
    need(all(type(v) is dict and type(v.get('security_id')) is str for v in state.pending),
         'ALL_PENDING_IDENTITIES_MUST_BE_REPRESENTED')
    return dict(episodes=deepcopy(state.wealth_core['episodes']),pending=deepcopy(state.pending),
                selected=deepcopy(state.median5['selected']))


def require_scope(prior,action):
    value=roles(prior);sid=action['source_security_id']
    held=[e for _,e in sorted(value['episodes'].items(),key=lambda item:int(item[0])) if e['security_id']==sid]
    need(not any(p['security_id']==sid for p in value['pending']),
         'UNSUPPORTED_SOURCE_PENDING_INTENT_REFUSES')
    need(not any(e.get('exit_pending',False) for e in held),'UNSUPPORTED_SOURCE_EPISODE_EXIT_FLAG_REFUSES')
    if action['clock_scope']=='DAILY_MARKET_UNHELD_SOURCE':
        need(not held,'DAILY_MARKET_CLOCK_CANNOT_SETTLE_SOURCE_HOLDING')
    if held and action['exchange_ratio'] is not None:
        ratio=Fraction(action['exchange_ratio'])
        quantities=[Fraction(str(e['current_shares'])) for e in held]
        total=sum(quantities,Fraction(0));whole=total*ratio
        need(total>0 and whole.denominator==1 and Fraction.from_float(float(whole))==whole,
             'UNSUPPORTED_NONINTEGRAL_HOLDER_ENTITLEMENT_WITHOUT_CIL_PRICE')
        delivered_so_far=0.0
        for index,(e,quantity) in enumerate(zip(held,quantities)):
            expected=quantity*ratio
            actual=float(whole)-delivered_so_far if index==len(held)-1 else float(whole*quantity/total)
            need(math.isfinite(actual) and actual>0 and Fraction.from_float(actual)==expected,
                 'UNSUPPORTED_INEXACT_CANONICAL_EPISODE_ALLOCATION')
            delivered_so_far+=actual
            reference=Fraction(str(e['initial_shares']))*ratio
            need(reference>0 and reference.denominator==1
                 and max(1,int(round(float(e['initial_shares'])*float(ratio))))==reference,
                 'UNSUPPORTED_CANONICAL_INITIAL_REFERENCE_ROUNDING')
        need(Fraction.from_float(delivered_so_far)==whole,'EXACT_CANONICAL_HOLDER_ALLOCATION_CONSERVATION')
    return value


class ActionGuard:
    def __init__(self,book,*,qualified=None,target_independence_qualified=False,held_target_holding_qualified=False):
        self.book=Path(book);self.records=facts()['records'];self.qualified=qualified
        self.target_independence_qualified=target_independence_qualified
        self.held_target_holding_qualified=held_target_holding_qualified
        self.observed=[];self.components=[];self.action_checks=[];self.pre_events=[];self.native_checks=[]
        self.native_scopes={}

    def archive(self,path,saved):
        target=self.original_archive(path,saved)
        if (Path(path).resolve().parent==(self.book/'pre-event').resolve()
                and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\.json\.gz',Path(path).name)):
            need(saved['sha256']==digest({k:v for k,v in saved.items() if k!='sha256'})
                 and saved['run']['input_sha256']==digest(dict(base=saved['base'],repairs=saved['repairs']))
                 and saved['base']['sources']==self.backtest.source_files()
                 and saved['source_cursor']==saved['run']['state']['last_processed_session']<Path(path).name[:10],
                 'NEWLY_BUILT_CANONICAL_PRE_EVENT_SOURCE_INPUT_COMMITMENTS')
            need(set(saved['journals'])=={'daily','formation','monthly','watch'},'PRE_EVENT_ALL_FOUR_PREFIX_COMMITMENTS')
            for name,commitment in saved['journals'].items():
                raw=(self.book/(name+'.jsonl')).read_bytes();prefix=raw[:commitment['bytes']]
                need(len(prefix)==commitment['bytes'] and sha(prefix)==commitment['prefix_sha256']
                     and (sha(prefix.splitlines(keepends=True)[-1]) if prefix else None)==commitment['last_record_sha256'],
                     'PRE_EVENT_EVERY_ACTUAL_JOURNAL_PREFIX_BEFORE_CURRENT_WRITE')
            restored=self.runtime.restore(saved['run'],policy=saved['base']['policy'],
                                          input_sha256=saved['run']['input_sha256'])
            need(self.runtime.checkpoint(restored)==saved['run'],'PRE_EVENT_CANONICAL_FULL_RESTORE_BEFORE_DURABLE_CURRENT')
            self.backtest.write_checkpoint(self.book/'checkpoint.json.gz',saved)
            need(self.journal.read_checkpoint(self.book/'checkpoint.json.gz')==saved,
                 'DURABLE_CURRENT_EXACT_NEWLY_ARCHIVED_PRE_EVENT_MAPPING')
        return target

    def relevant(self,state,packet):
        ordinary=self.original_relevant(state,packet)
        selected=set(state.median5['selected'])
        registered={a['source_security_id'] for a in self.records if a['economic_session']==packet.day}
        extra=[material(t) for t in packet.terminal if t.security_id in selected|registered]
        if not extra:return ordinary
        result=deepcopy(ordinary) if ordinary else dict(terminal=[],spinoff=[])
        known={digest(t) for t in result['terminal']}
        result['terminal'].extend(t for t in extra if digest(t) not in known)
        return result

    def pre_event(self,run,day):
        from research.pooled_vacancy_funding import journal
        exact=[];expected=self.runtime.checkpoint(run)
        for path in (self.book/'pre-event').glob(day+'-*.json.gz'):
            c=journal.read_checkpoint(path)
            if c['run']==expected:exact.append((path,c))
        need(len(exact)==1,'ACTUAL_CANONICAL_PRE_EVENT_CHECKPOINT_REQUIRED_BEFORE_GUARD')
        path,c=exact[0]
        need(c['source_cursor']==run.state.last_processed_session
             and c['sha256']==digest({k:v for k,v in c.items() if k!='sha256'})
             and c['run']['input_sha256']==digest(dict(base=c['base'],repairs=c['repairs'])),
             'ACTUAL_PRE_EVENT_FULL_SOURCE_INPUT_AND_FINANCIAL_COMMITMENTS')
        restored=self.runtime.restore(c['run'],policy=run.policy,input_sha256=run.input_sha256)
        need(self.runtime.checkpoint(restored)==expected,'ACTUAL_PRE_EVENT_CHECKPOINT_CANONICAL_RESTORE')
        # archive() already saved the identical mapping before publication.
        current_path=self.book/'checkpoint.json.gz'
        need(journal.read_checkpoint(current_path)==c,'SAVED_CURRENT_EXACT_FULL_PRE_EVENT_CHECKPOINT_MAPPING')
        row=dict(session=day,path=path.name,outer_sha256=c['sha256'],inner_sha256=expected['checkpoint_sha256'],
                 state_sha256=expected['state_sha256'],prior_session=c['source_cursor'],
                 current_saved_identical_before_guard=True,
                 current_file=dict(bytes=current_path.stat().st_size,sha256=sha(current_path.read_bytes())))
        if row not in self.pre_events:self.pre_events.append(row)
        return row

    def advance(self,run,published):
        day=published.session;before=roles(run.state)
        active=[a for a in self.records if a['economic_session']==day]
        terms={t.security_id:t for t in published.terminal_events}
        needs_cp=bool(active) or any(t.security_id in set(before['selected']) or (
            (day,t.security_id) in self.native_scopes and (any(e['security_id']==t.security_id
                for e in before['episodes'].values()) or any(p['security_id']==t.security_id for p in before['pending'])))
            for t in published.terminal_events)
        if needs_cp:self.pre_event(run,day)
        for a in active:
            need(a['source_security_id'] in terms
                 and material(terms[a['source_security_id']])==term(a),'EXACT_TYPED_ECONOMIC_TERM_AT_USE')
            actual=require_scope(run.state,a)
            target=a['delivered_security_id']
            target_present=target is not None and (any(e['security_id']==target for e in actual['episodes'].values())
                or any(p['security_id']==target for p in actual['pending']))
            if target_present:
                if any(e['security_id']==a['source_security_id'] for e in actual['episodes'].values()):
                    need(not any(p['security_id']==target for p in actual['pending']),
                         'UNQUALIFIED_HELD_SOURCE_WITH_TARGET_PENDING_REFUSES')
                    need(not any(e['security_id']==target and e.get('exit_pending',False)
                                 for e in actual['episodes'].values()),
                         'UNQUALIFIED_HELD_SOURCE_WITH_TARGET_EXIT_FLAG_REFUSES')
                    need(self.held_target_holding_qualified,'HELD_SOURCE_TARGET_HOLDING_COMPONENT_REQUIRED')
                else:
                    need(self.target_independence_qualified,'TARGET_ROLE_INDEPENDENCE_MUST_BE_ACTUALLY_QUALIFIED')
            self.action_checks.append(dict(action_id=a['action_id'],session=day,
                source_held=any(e['security_id']==a['source_security_id'] for e in actual['episodes'].values()),
                source_pending=False,source_selected=a['source_security_id'] in actual['selected'],
                target_existing_role=target_present,clock_scope=a['clock_scope']))
        for t in published.terminal_events:
            key=(day,t.security_id)
            if key in self.native_scopes:
                value=roles(run.state)
                need(not any(e['security_id']==t.security_id for e in value['episodes'].values())
                     and not any(p['security_id']==t.security_id for p in value['pending']),
                     'INHERITED_UNHELD_NATIVE_SCOPE_CANNOT_SETTLE_SOURCE_POSITION_OR_INTENT')
                self.native_checks.append(dict(session=day,security_id=t.security_id,unheld=True,all_source_pending_absent=True,
                                               source_record_sha256=self.native_scopes[key]))
            if t.security_id in set(before['selected']):
                need(t.completeness(0)[0],'UNRESOLVED_SELECTED_ACTION_REFUSES_BEFORE_TRANSITION')
        previous=self.runtime.checkpoint(run) if day in ('2020-02-05','2020-02-06') else None
        following=self.original_advance(run,published)
        if previous is not None:
            checkpoint=self.runtime.checkpoint(following)
            restored=self.runtime.restore(checkpoint,policy=following.policy,input_sha256=following.input_sha256)
            need(self.runtime.checkpoint(restored)==checkpoint,'ACTUAL_TWO_SESSION_FULL_CANONICAL_ROUNDTRIP')
            row=dict(session=day,prior_state_sha256=previous['state_sha256'],state_sha256=checkpoint['state_sha256'],
                     before=before,after=roles(following.state))
            if self.qualified is not None:
                need(row==self.qualified[len(self.observed)],'FRESH_FINANCE_EXACT_QUALIFIED_TWO_SESSION_FULL_STATE_AND_ROLES')
            self.observed.append(row)
            self.components.append(dict(session=day,prior_checkpoint=previous,publication=material(published),checkpoint=checkpoint))
        return following

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import runtime,backtest,journal
        rows=json.loads(Path('/frozen/bundle/supplements.json').read_bytes())
        corrected={a['source_security_id'] for a in self.records}
        for row in rows:
            if row.get('security_id') not in corrected and ('UNHELD' in row.get('disposition','').upper()
                    or 'unheld' in row.get('reference','').lower()):
                self.native_scopes[(row['effective_session'],row['security_id'])]=digest(row)
        self.runtime,self.backtest,self.journal=runtime,backtest,journal
        self.original_advance,self.original_relevant=runtime.advance,backtest.relevant
        self.original_archive=backtest.archive_checkpoint
        runtime.advance=self.advance;backtest.relevant=self.relevant;backtest.archive_checkpoint=self.archive;return self

    def __exit__(self,*args):
        self.runtime.advance=self.original_advance;self.backtest.relevant=self.original_relevant
        self.backtest.archive_checkpoint=self.original_archive
