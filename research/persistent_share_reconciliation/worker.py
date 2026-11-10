"""Hosted fixed-decision share reconciliation. No strategy/controller transition.

The DTOs below are recorded trace views, never SessionState or production
authority. Scalar legacy arithmetic runs in a separate import namespace/process.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from fractions import Fraction as F
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS


START = '2018-01-02'
END = '2019-02-05'
COUNT = 275
BIL = 'SENTINEL:BIL'
PREFIX_SHA = '9f1c682846167a1deafe4496aa4d2e6b803f5650d9f2265b34c691bae56067b2'
PREFIX_BYTES = 170330724
CP_SHA = '6942c696c752ee35d8a215a6ad138c71a69d9d8dd1337dcaa01519c3e141ea56'


def need(value, reason):
    if not value:
        raise ValueError(reason)


def hosted():
    need(os.environ.get('PERSISTENT_RECONCILIATION_HOSTED') == '1'
         and str(Path(__file__).resolve()).startswith('/current/research/persistent_share_reconciliation/'),
         'HOSTED_RECONCILIATION_ONLY')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    need(not path.exists(), 'OUTPUT_COLLISION:' + path.name)
    path.write_bytes(encoded(value) + b'\n')


class Journal:
    def __init__(self, path):
        hosted()
        self.path = path
        self.raw = path.open('xb')
        self.stream = gzip.GzipFile(filename='', fileobj=self.raw, mode='wb', mtime=0)
        self.h = hashlib.sha256()
        self.bytes = self.records = 0

    def add(self, value):
        raw = encoded(value) + b'\n'
        self.stream.write(raw)
        self.h.update(raw)
        self.bytes += len(raw)
        self.records += 1

    def prefix(self):
        return dict(records=self.records, bytes=self.bytes, sha256=self.h.hexdigest())

    def close(self):
        self.stream.close()
        self.raw.close()
        return {**self.prefix(), 'file_sha256': file_sha(self.path)}


def records(path):
    with gzip.open(path, 'rt') as stream:
        return [json.loads(line) for line in stream]


def verify_inputs(args):
    hosted()
    transfer=json.loads((args.current/'research/persistent_share_reconciliation/input-transfer.json').read_bytes())
    manifest_raw=(args.input/'manifest.json').read_bytes()
    need(hashlib.sha256(manifest_raw).hexdigest()==transfer['manifest_sha256'],'EXACT_INPUT_TRANSFER_MANIFEST')
    manifest=json.loads(manifest_raw)
    need(manifest['schema']=='research.capital-risk-inputs/1'
         and manifest['purpose']=='FIXED_ACCOUNT_RECONCILIATION_BIL'
         and manifest['legacy_commit']=='0bc38753ac1f85b31eb95f560720e6b037e892c5', 'EXACT_INPUT_SCOPE')
    need(manifest['protocol_sha256']==file_sha(args.current/'docs/core-sentinel-reconciliation-20261109.md'), 'EXACT_FROZEN_PROTOCOL')
    actual={p.relative_to(args.input).as_posix() for p in args.input.rglob('*') if p.is_file() and p.relative_to(args.input).as_posix()!='manifest.json'}
    need(actual==set(manifest['members']),'EXACT_INPUT_MEMBER_SET')
    for name,spec in manifest['members'].items():
        named=args.input/name;path=named.resolve()
        need(path.is_relative_to(args.input.resolve()) and not named.is_symlink(),'INPUT_MEMBER_PATH')
        need(path.stat().st_size==spec['bytes'] and file_sha(path)==spec['sha256'],'EXACT_INPUT_MEMBER:'+name)
    return dict(manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),protocol_sha256=manifest['protocol_sha256'],members=manifest['members'])


def paths(args, *, scalar=False):
    hosted()
    required = (args.source, args.legacy, args.current, args.p00, args.input)
    need(all(p.is_dir() for p in required), 'EXACT_HOSTED_MOUNTS')
    need(tuple(map(str, required)) == ('/variant', '/legacy', '/current', '/p00', '/input'), 'UNEXPECTED_MOUNT_CONTEXT')
    preferred = ([str(args.source), str(args.source/'shared'), str(args.legacy),
                  str(args.legacy/'shared'), str(args.legacy/'research/capital_risk')]
                 if scalar else
                 [str(args.current), str(args.current/'shared'), str(args.legacy/'research/capital_risk'),
                  str(args.legacy), str(args.legacy/'shared')])
    sys.path[:] = preferred + [p for p in sys.path if p not in preferred and p not in ('/variant', '/variant/shared')]
    os.environ['HOLDING_QUAL_HOSTED'] = '1'


def load_source(root):
    hosted()
    book = root/'book'
    need(file_sha(book/'checkpoint.json.gz') == CP_SHA, 'EXACT_CHECKPOINT_FILE')
    # The exact retained gzip bytes are authenticated above. Decode DATA only:
    # importing the original journal package here would require /variant and
    # contaminate the current-canonical parent process's import namespace.
    cp = json.loads(gzip.decompress((book/'checkpoint.json.gz').read_bytes()))
    need(cp['sha256']=='352d3ad9c74d29d34faae0e07a1a592bc9b6921259a016298bd93e62c7188978','EXACT_CHECKPOINT_PAYLOAD_IDENTITY')
    spec = cp['journals']['daily']
    need(spec['bytes'] == PREFIX_BYTES and spec['prefix_sha256'] == PREFIX_SHA, 'EXACT_DAILY_COMMITMENT')
    path=book/'daily.jsonl'
    need(path.stat().st_size == PREFIX_BYTES and file_sha(path) == PREFIX_SHA, 'EXACT_COMMITTED_DAILY_BYTES')
    pilot=[];line_count=0
    with path.open('rb') as stream:
        for line in stream:
            if line_count<COUNT:pilot.append(json.loads(line))
            line_count+=1
    need(line_count == cp['completed'] == 2156, 'SOURCE_AXIS_COUNT')
    need(len(pilot) == COUNT and pilot[0]['session'] == START and pilot[-1]['session'] == END, 'FIXED_275_PILOT')
    events = cp['run']['state']['ledger']['events']
    return pilot, events, dict(checkpoint_sha256=CP_SHA, daily_sha256=PREFIX_SHA, daily_bytes=PREFIX_BYTES,
                               checkpoint_inner_sha256=cp['sha256'], immutable_decisions_sha256=digest([r['decision'] for r in pilot]))


def bil_input(folder, sessions):
    hosted()
    raw = (folder/'bil-input.json').read_bytes()
    data = json.loads(raw)
    bars = data.get('daily', data.get('bars'))
    if isinstance(bars, list):
        bars = {r['session']: r for r in bars}
    need(isinstance(bars, dict), 'BIL_DAILY_MAP_REQUIRED')
    need(all(s in bars for s in sessions) and '2017-12-29' in bars, 'BIL_COMPLETE_AXIS')
    need(set(bars)==set(sessions)|{'2017-12-29'},'EXACT_BIL_AXIS_WITH_PREDECESSOR')
    actions = data.get('actions', [])
    need(isinstance(actions, list), 'BIL_ACTION_RECORDS_REQUIRED')
    # The capture's status is an independent DATA qualification, not authority
    # inferred from presence of prices or the producer's requested outcome.
    qualification = data.get('qualification', {})
    status = qualification.get('status', data.get('status'))
    need(data.get('schema')=='research.p00-bil-input/1' and data.get('qualified') is True
         and data.get('unknown_terms')==[] and status=='QUALIFIED_BIL_PRICE_AND_PAYABLE_TERMS', 'BIL_NOT_QUALIFIED:' + str(status))
    for a in actions:
        ex = a.get('ex_date')
        if ex and START <= ex <= END:
            need(a.get('payable_date') and a.get('rate') is not None,
                 'UNKNOWN_BIL_PAYABLE_TERMS')
            need(a.get('currency') == 'USD' and a.get('foreign') is False, 'BIL_UNSUPPORTED_CURRENCY')
            need(a.get('security_id')==BIL and a.get('symbol')=='BIL' and a.get('record_date')
                 and date.fromisoformat(a['payable_date'])>=date.fromisoformat(ex), 'BIL_EXACT_ECONOMIC_TERMS')
            need(D(str(a['rate'])).is_finite() and D(str(a['rate'])) >= 0, 'BIL_INVALID_CASH_RATE')
    for s in ['2017-12-29'] + sessions:
        for name in ('raw_open', 'raw_close', 'split_open', 'split_close', 'all_open', 'all_close'):
            value = D(str(bars[s][name]))
            need(value.is_finite() and value > 0, 'BIL_INVALID_' + name)
        need(D(str(bars[s]['raw_open'])) == D(str(bars[s]['split_open']))
             and D(str(bars[s]['raw_close'])) == D(str(bars[s]['split_close'])), 'PILOT_BIL_SPLIT_NOT_SUPPORTED')
    return data, bars, actions, dict(file_sha256=hashlib.sha256(raw).hexdigest(), schema=data.get('schema'), qualification=qualification)


def scalar(args):
    hosted()
    paths(args, scalar=True)
    input_proof=verify_inputs(args)
    from full_system_controller_worker import actual_account, independently_check
    rows, events, source = load_source(args.p00)
    _, bars, _, bil_proof = bil_input(args.input, [r['session'] for r in rows])
    args.output.mkdir(parents=True, exist_ok=False)
    journals = {a: Journal(args.output/(a+'.jsonl.gz')) for a in ('S', 'A')}
    priors = {'S': None, 'A': None}
    previous = '2017-12-29'
    try:
        for i, original in enumerate(rows):
            for arm in ('S', 'A'):
                row = deepcopy(original)
                if arm == 'A':
                    b, p = bars[row['session']], bars[previous]
                    # Unchanged scalar reader's adjusted-open formula becomes
                    # all_open when signal open/close are the split domain.
                    row['economics']['strategy_prices'] = dict(
                        bil_open_signal=str(b['all_open']), bil_close_signal=str(b['all_close']),
                        bil_close_adjusted=str(b['all_close']), bil_close_unadjusted=str(b['raw_close']),
                        bil_previous_close_adjusted=str(p['all_close']),
                        bil_previous_session=previous)
                if i == 0:
                    value = deepcopy(original['economics'])
                    if arm == 'A':
                        # Anchor has no accrued return or trade; it still names
                        # the source bridge which will supply the next factors.
                        value['strategy_prices'] = row['economics']['strategy_prices']
                        value['strategy_prices_sha256'] = digest(value['strategy_prices'])
                else:
                    value = actual_account(priors[arm], row, row['decision']['target_core_exposure'], events)
                    independently_check(priors[arm], row, value, events)
                if arm == 'S':
                    need(value == original['economics'], 'EXACT_S_ALL_ECONOMIC_FIELDS:' + row['session'])
                journals[arm].add(dict(arm=arm, session=row['session'], economics=value))
                priors[arm] = json.loads(json.dumps(value))
            previous = original['session']
        proofs = {a: journals[a].close() for a in journals}
    except BaseException:
        for journal in journals.values():
            try: journal.close()
            except Exception: pass
        raise
    need(str(sys.modules['sentinel.shadow_observation'].__file__).startswith('/variant/'),'EXACT_LEGACY_SCALAR_NAMESPACE')
    write(args.output/'proof.json', dict(status='SCALAR_ARMS_REVIEW_REQUIRED', source=source, bil=bil_proof,
                                        journals=proofs, exact_S_fields=COUNT, no_strategy_steps=True,
                                        input=input_proof,imported_shadow_observation=str(sys.modules['sentinel.shadow_observation'].__file__)))


def trace_dto(row):
    close = row['evidence']['research_entry_audit']['closing_accounting']
    return NS(last_processed_session=row['session'], wealth_core=deepcopy(close['wealth_core']),
              pending=deepcopy(close['pending']), last_decision=deepcopy(row['decision']))


def dto_json(dto):
    # ownership/carry need only these exact trace fields. This is deliberately
    # not a fabricated canonical SessionState envelope.
    return dict(last_processed_session=dto.last_processed_session,
                wealth_core={'episodes': deepcopy(dto.wealth_core['episodes'])}, pending=deepcopy(dto.pending),
                last_decision=deepcopy(dto.last_decision))


def ns_plan(raw):
    return NS(target_exposure=D(raw['target_exposure']), decision_session=date.fromisoformat(raw['decision_session']),
              target_basket={s:D(q) for s,q in raw['target_basket'].items()},
              opening_intents=tuple(NS(**o) for o in raw['opening_intents']))


def ns_projection(raw):
    return NS(target_basket={s:D(q) for s,q in raw['target_basket'].items()},
              through_session=date.fromisoformat(raw['through_session']),
              action_multipliers={s:D(q) for s,q in raw.get('action_multipliers',{}).items()},
              action_evidence=tuple(raw.get('action_evidence',[])), opening_sizing=raw.get('opening_sizing'))


class ShareArm:
    def __init__(self, arm, identity, event_journal):
        hosted()
        from holding_account import Account, snapshot
        self.arm, self.identity, self.events = arm, identity, event_journal
        self.account = Account(source_sha256=identity, cash='50000')
        self.initial = snapshot(self.account)
        self.pending = self.previous_state = self.previous_plan = self.previous_projection = None
        self.last_nav = F(50000)
        self.fees = F(0)
        self.traded = F(0)
        self.restore_count = 0
        self.checkpoint_chain = '0'*64

    def apply(self, pair, context):
        from holding_account import snapshot
        before = snapshot(self.account)
        self.account, record = pair
        self.events.add(dict(arm=self.arm, before_state_sha256=before['state_sha256'], record=record, context=context))
        fee = record['event'].get('fees', '0')
        self.fees += F(fee)
        if record['event']['operation'] in ('BUY', 'SELL'):
            self.traded += F(record['event']['filled_shares'])*F(record['event']['raw_price'])
        return record

    def actions(self, day, source_events, all_events, bars, bil_actions, prior_plan):
        from holding_account import accrue, pay, cash_merger, snapshot
        from holding_actions import Terms, convert
        from stock_strategy_shared.wealth_core.terminal import _split_entitlement
        target = dict(prior_plan['desired_basket'])
        for ix, event in enumerate(source_events):
            sid, kind = event['security_id'], event['event_type']
            held = any(p.security_id == sid for p in self.account.positions.values())
            context = dict(source_event=event, source_event_sha256=digest(event))
            event_id = day+'/CORE_ACTION/'+str(ix)
            if kind == 'DIVIDEND_ACCRUED' and held:
                matches = [e for e in all_events if e['event_type']=='DIVIDEND_PAID' and e['security_id']==sid
                           and e['detail']['accrued_session']==day]
                need(len(matches)==1, 'EXACT_SOURCE_PAY_DATE')
                context['dividend_terms']=dict(security_id=sid,ex_date=day,pay_date=matches[0]['session'],cash_per_share=str(event['price']))
                self.apply(accrue(self.account,event_id=event_id,session=day,claim_id=sid+'/'+day,
                                 security_id=sid,cash_per_share=str(event['price']),pay_session=matches[0]['session']), context)
            elif kind == 'DIVIDEND_PAID' and sid+'/'+event['detail']['accrued_session'] in self.account.claims:
                self.apply(pay(self.account,event_id=event_id,session=day,claim_id=sid+'/'+event['detail']['accrued_session']),context)
            elif kind == 'CASH_MERGER':
                if held:
                    self.apply(cash_merger(self.account,event_id=event_id,session=day,security_id=sid,
                                           cash_per_share=str(event['price'])),context)
                target.pop(sid,None)
            elif kind == 'CONVERSION':
                detail=event['detail'];need(day=='2018-09-04' and event['ticker']=='ILG', 'DECLARED_ILG_CONVERSION_ONLY')
                ratio=str(detail['exchange_ratio_exact']);delivered=detail['delivered_security_id']
                need(ratio=='0.165' and F(str(event['price']))==F('14.75')
                     and F(str(detail['reference_rebase']['delivered_raw_open']))==F('118.45'), 'EXACT_INHERITED_ILG_TERMS')
                if held:
                    terms=Terms(event_id=event_id,session=day,security_id=sid,delivered_security_id=delivered,
                                delivered_ticker=detail['delivered_ticker'],ratio=ratio,cash_per_share=F('14.75'),
                                cil_price=F('118.45'),reference=detail['reference'],input_sha256=prior_plan['source_input_sha256'],
                                predecessor_sha256=snapshot(self.account)['state_sha256'])
                    self.apply(convert(self.account,terms,canonical_entitlement=_split_entitlement,
                                       canonical_cil=lambda fraction,terms:fraction*terms.cil_price), context)
                if sid in target:
                    whole,_ = _split_entitlement(F(target.pop(sid)),ratio)
                    target[delivered]=str(whole)
            elif kind not in ('BUY','SELL','DIVIDEND_ACCRUED','DIVIDEND_PAID'):
                need(not held and sid not in target, 'UNSUPPORTED_HELD_SOURCE_ACTION:' + kind)
        for ix, event in enumerate(bil_actions):
            if event.get('ex_date') == day and any(p.security_id==BIL for p in self.account.positions.values()):
                self.apply(accrue(self.account,event_id=day+'/BIL_EX/'+str(ix),session=day,claim_id='BIL/'+str(event['id']),
                                 security_id=BIL,cash_per_share=str(event['rate']),pay_session=event['payable_date']),
                           dict(bil_action=event,bil_action_sha256=digest(event),dividend_terms=dict(security_id=BIL,ex_date=day,
                                pay_date=event['payable_date'],cash_per_share=str(event['rate']))))
        for key, claim in sorted(self.account.claims.items()):
            if key.startswith('BIL/') and claim.pay_session<=day:
                self.apply(pay(self.account,event_id=day+'/BIL_PAY/'+key,session=day,claim_id=key), dict(claim_id=key))
        return target

    def close_plan(self, row, next_day, marks):
        from sentinel.execution.projection import project, desired_basket
        from sentinel.execution.held_targets import carry_quantities, apply, ownership
        from sentinel.core.decision import ShadowTarget
        from sentinel.execution.plan import OpeningIntent
        from sentinel.execution.numeric import exact_decimal
        from holding_account import mark
        dto = trace_dto(row)
        episodes = dto.wealth_core['episodes']
        shares={}
        identities={}
        for ep in episodes.values():
            sid=str(ep['security_id']);need(sid not in identities,'PILOT_DUPLICATE_SECURITY_EPISODES')
            identities[sid]=dict(episode=ep['signal_date']+'/'+str(ep['slot_id']),ticker=ep['ticker'],slot_id=ep['slot_id'])
            shares[sid]=D(str(ep['current_shares']))
        intents=[]
        for order in dto.pending:
            sid=str(order['security_id'])
            if order['operation']=='CLOSE_POSITION':
                shares[sid]=shares.get(sid,D(0))-D(str(order['shares']))
            elif order['operation']=='OPEN_SLOT_POSITION':
                need(D(str(order['shares']))==0 and order.get('intended_dollars') is not None, 'V5_DOLLAR_INTENT_REQUIRED')
                intents.append(OpeningIntent(sid,int(order['slot_id']),D(str(order['intended_dollars']))))
                identities[sid]=dict(episode=order['signal_session']+'/'+str(order['slot_id']),ticker=order['ticker'],slot_id=order['slot_id'])
            else: raise ValueError('UNSUPPORTED_PENDING_OPERATION')
        shares={s:q for s,q in shares.items() if q>0}
        target=ShadowTarget(shares=shares,tickers={s:v['ticker'] for s,v in identities.items()},opening_intents=tuple(sorted(intents,key=lambda v:v.slot_id)))
        nav=mark(self.account,{p.security_id:marks[p.security_id] for p in self.account.positions.values()})
        claims=sum((c.amount for c in self.account.claims.values()),F(0))
        sizing=nav-claims
        exposure=D(str(row['decision']['target_core_exposure']))
        core_nav=D(str(row['economics']['parent_core_close_equity']))
        weights={s:exact_decimal(F(q)*F(marks[s])) for s,q in shares.items()}
        kwargs=dict(shadow_weights=weights,exposure=exposure,nav=exact_decimal(sizing),marks={s:D(v) for s,v in marks.items()},
                    defensive_security=BIL,defensive_weight=D(1)-exposure,weight_denominator=core_nav)
        raw=project(**kwargs)
        retained=None
        if self.arm=='P':
            retained={} if self.previous_plan is None else carry_quantities(previous=ns_plan(self.previous_plan),
                previous_state=NS(**self.previous_state),projection=ns_projection(self.previous_projection),state=dto,exposure=exposure)
        final=apply(raw,targets=retained,canonical_target=target,marks=kwargs['marks'])
        desired={s:str(q) for s,q in desired_basket(final).items()}
        for intent in intents:desired[intent.security_id]='0'
        current_ownership=ownership(dto)
        for sid in current_ownership:
            desired.setdefault(sid,'0')
        plan=dict(signal_session=row['session'],execution_session=next_day,target_exposure=str(exposure),
                  source_state_sha256=row['state_sha256'],source_input_sha256=row['input_sha256'],
                  source_chain_sha256=row['chain_sha256'],decision_sha256=digest(row['decision']),
                  nav=str(sizing),core_nav=str(core_nav),desired_basket=desired,identities=identities,
                  opening_intents=[i.to_dict() for i in intents],retained_targets=None if retained is None else {s:str(q) for s,q in retained.items()},
                  closing_marks=marks,ownership=current_ownership,canonical_target_shares={s:str(q) for s,q in shares.items()})
        audit=dict(scope='RECORDED_TRACE_DTO_PURE_PROJECTION_ONLY',project_kwargs={k:({s:str(q) for s,q in v.items()} if isinstance(v,dict) else str(v) if isinstance(v,D) else v) for k,v in kwargs.items()},
                   canonical_target=dict(shares={s:str(q) for s,q in shares.items()},tickers=target.tickers,opening_intents=plan['opening_intents']),
                   state=dto_json(dto),prior_state=self.previous_state,previous_plan=self.previous_plan,
                   predecessor_projection=self.previous_projection,retained_targets=plan['retained_targets'],
                   raw_projection=raw.to_dict(),final_projection=final.to_dict(),desired_basket=desired,ownership=current_ownership)
        self.pending=plan
        self.previous_state=dto_json(dto)
        self.previous_plan=dict(target_exposure=str(exposure),decision_session=row['session'],target_basket=desired,opening_intents=plan['opening_intents'])
        self.previous_projection=dict(target_basket=desired,through_session=row['session'],action_multipliers={},action_evidence=[])
        return plan,audit,nav,sizing

    def open(self,row,source_events,all_events,bars,bil_actions,opens):
        from holding_account import Intent,RawOpen,trade,commit
        from stock_strategy_shared.wealth_core.v5 import opening_quantity
        from sentinel.execution.projection import Projection
        from sentinel.execution.held_targets import apply
        from sentinel.core.decision import ShadowTarget
        from sentinel.execution.plan import OpeningIntent
        from sentinel.execution.numeric import exact_decimal
        day=row['session'];plan=self.pending
        need(plan['execution_session']==day and plan['signal_session']<day,'EXACT_NEXT_OPEN_TIMING')
        desired=self.actions(day,source_events,all_events,bars,bil_actions,plan)
        core_targets={s:D(q) for s,q in plan['canonical_target_shares'].items()}
        identities=deepcopy(plan['identities'])
        for event in source_events:
            if event['event_type']=='CONVERSION':
                old,new=event['security_id'],event['detail']['delivered_security_id']
                if old in identities:identities[new]={**identities.pop(old),'ticker':event['detail']['delivered_ticker']}
                core_targets.pop(old,None);core_targets[new]=D(str(event['detail']['shares_delivered']))
            elif event['event_type']=='CASH_MERGER':
                identities.pop(event['security_id'],None);core_targets.pop(event['security_id'],None)
        entry_audit=[]
        for intent in plan['opening_intents']:
            sid=intent['security_id'];buys=[e for e in source_events if e['event_type']=='BUY' and e['security_id']==sid]
            need(len(buys)<=1,'UNIQUE_SOURCE_ENTRY_FILL')
            if not buys:
                desired[sid]='0';entry_audit.append(dict(intent=intent,status='SOURCE_NOT_FILLED',account_shares='0'))
                continue
            buy=buys[0];price=str(buy['price'])
            need(F(price)==F(opens[sid]),'SOURCE_BUY_RAW_OPEN_MATCH')
            core_qty=opening_quantity(intended=float(intent['intended_dollars']),cash=float(buy['cash_before']),price=float(price),cost_bps=10)
            need(F(str(buy['shares_delta']))==core_qty,'CANONICAL_OPENING_QUANTITY_MATCHES_FIXED_CORE')
            scaled=F(core_qty)*F(plan['target_exposure'])*F(plan['nav'])/F(plan['core_nav'])
            desired[sid]=str(scaled//1)
            core_targets[sid]=D(core_qty)
            entry_audit.append(dict(intent=intent,status='SOURCE_FILLED',source_buy=buy,canonical_core_shares=core_qty,account_shares=desired[sid]))
        # Reuse canonical headroom enforcement after new dollar-intent shares
        # become bindable at the execution open. Retained values use the same
        # original close references; new entry quantities use their RAW open.
        refs={s:D(v) for s,v in plan['closing_marks'].items()}
        for intent in plan['opening_intents']:
            sid=intent['security_id']
            if sid in opens:refs[sid]=D(opens[sid])
        for event in source_events:
            if event['event_type']=='CONVERSION':
                refs.pop(event['security_id'],None);refs[event['detail']['delivered_security_id']]=D(opens[event['detail']['delivered_security_id']])
        quantities={s:D(q) for s,q in desired.items() if s!=BIL and D(q)>0}
        p=Projection(target_exposure=D(plan['target_exposure']),nav=exact_decimal(F(plan['nav'])),quantities=quantities,
                     notional={s:exact_decimal(F(q)*F(refs[s])) for s,q in quantities.items()},
                     defensive_security=BIL,defensive_quantity=D(desired.get(BIL,'0')))
        target=ShadowTarget(shares=core_targets,tickers={},opening_intents=tuple(OpeningIntent(i['security_id'],i['slot_id'],D(i['intended_dollars'])) for i in plan['opening_intents']))
        retained=plan['retained_targets']
        # The predeclared material-action ownership bridge cannot be mistaken
        # for a scalar split by canonical carry/apply.
        if retained is not None:
            retained={s:D(q) for s,q in retained.items() if s in quantities or s==BIL}
            for event in source_events:
                if event['event_type']=='CONVERSION':
                    retained.pop(event['security_id'],None)
                    delivered=event['detail']['delivered_security_id']
                    if delivered in desired:
                        # The authenticated material bridge carries the prior
                        # intended entitlement through this open only. The
                        # ensuing close sees changed SID ownership and resets.
                        retained[delivered]=D(desired[delivered])
        before_apply=p.to_dict()
        p=apply(p,targets=retained,canonical_target=target,marks=refs)
        headroom_audit=dict(raw_projection=before_apply,final_projection=p.to_dict(),marks={s:str(v) for s,v in refs.items()},
                            retained_targets=None if retained is None else {s:str(q) for s,q in retained.items()},
                            canonical_target_shares={s:str(q) for s,q in core_targets.items()},opening_intents=plan['opening_intents'])
        desired={s:str(q) for s,q in p.quantities.items()};desired[BIL]=str(p.defensive_quantity)
        identities[BIL]=dict(episode='DEFENSIVE:BIL',ticker='BIL',slot_id=-1)
        allowed=plan['ownership']
        converted={e['detail']['delivered_security_id'] for e in source_events if e['event_type']=='CONVERSION'}
        def fill(sid,quantity,side,episode,core_exit):
            meta=identities.get(sid)
            existing=self.account.positions.get(episode)
            ticker=existing.ticker if existing is not None else meta['ticker']
            intent=Intent(event_id=day+'/'+side+'/'+episode,signal_session=plan['signal_session'],execution_session=day,
                          episode=episode,security_id=sid,ticker=ticker,kind='DEFENSIVE' if sid==BIL else 'EQUITY',
                          side=side,shares=quantity,source_episode_live=not core_exit,core_exit=core_exit)
            quote=RawOpen(session=day,security_id=sid,price=opens[sid])
            return self.apply(trade(self.account,intent,quote),dict(intent=intent.model_dump(mode='json'),quote=quote.model_dump(mode='json'),
                desired_shares=desired.get(sid,'0'),source_state_sha256=plan['source_state_sha256'],source_input_sha256=plan['source_input_sha256']))
        fills=[]
        for sid in sorted({p.security_id for p in self.account.positions.values()} | set(desired)):
            positions=[p for p in self.account.positions.values() if p.security_id==sid]
            need(len(positions)<=1,'UNIQUE_ACCOUNT_SECURITY_LOT')
            have=positions[0].shares if positions else F(0);want=F(desired.get(sid,'0'))
            if have>want:
                episode=positions[0].episode
                live=sid==BIL or sid in allowed or sid in converted
                # A fixed Core exit retires its causal episode; an allocation
                # reduction, including zero exposure, does not retire it.
                core_exit=sid!=BIL and not live
                fills.append(fill(sid,have-want,'SELL',episode,core_exit)['event'])
        for sid in sorted(desired):
            positions=[p for p in self.account.positions.values() if p.security_id==sid]
            have=positions[0].shares if positions else F(0);want=F(desired[sid])
            if want>have:
                need(sid in identities,'TARGET_LACKS_CAUSAL_EPISODE')
                episode=positions[0].episode if positions else identities[sid]['episode']
                quantity=(want-have)//1
                if quantity:fills.append(fill(sid,F(quantity),'BUY',episode,False)['event'])
        # Retire exits even if this account never funded the original episode.
        for sid,meta in sorted(identities.items()):
            key=meta['episode']
            if sid!=BIL and sid not in allowed and sid not in converted and key not in self.account.positions and key not in self.account.retired:
                self.apply(commit(self.account,event=dict(event_id=day+'/RETIRE/'+key,session=day,operation='CORE_EXIT_RETIRED',episode=key),
                                  retired=self.account.retired+(key,)),dict(source_state_sha256=plan['source_state_sha256']))
        self.previous_projection=dict(target_basket=desired,through_session=day,action_multipliers={},action_evidence=[],
                                      opening_sizing={'mode':'TRACE_DTO_IDEALIZED_RAW_OPEN','entries':entry_audit})
        return dict(signal_session=plan['signal_session'],held_target=plan['target_exposure'],desired_basket=desired,
                    intended_entry_sizing=entry_audit,headroom_audit=headroom_audit,fills=fills,actual_shares={p.security_id:str(p.shares) for p in self.account.positions.values()},
                    remaining={s:str(F(q)-sum((p.shares for p in self.account.positions.values() if p.security_id==s),F(0))) for s,q in desired.items()})

    def checkpoint(self):
        from holding_account import snapshot
        cp=dict(schema='research.fixed-share-reconciliation-checkpoint/1',arm=self.arm,source_sha256=self.identity,
                account=snapshot(self.account),pending=deepcopy(self.pending),previous_state=deepcopy(self.previous_state),
                previous_plan=deepcopy(self.previous_plan),previous_projection=deepcopy(self.previous_projection),last_nav=str(self.last_nav),
                cumulative_fees=str(self.fees),cumulative_traded_notional=str(self.traded),event_prefix=self.events.prefix(),
                previous_checkpoint_sha256=self.checkpoint_chain)
        cp['checkpoint_sha256']=digest(cp)
        material=json.loads(json.dumps(cp,allow_nan=False))
        self.restore_checkpoint(material,expected_sha256=cp['checkpoint_sha256'],expected_predecessor=self.checkpoint_chain,
                                expected_source_state=self.pending['source_state_sha256'],event_prefix=self.events.prefix())
        self.restore_count+=1
        return cp

    def restore_checkpoint(self,material,*,expected_sha256,expected_predecessor,expected_source_state,event_prefix):
        hosted()
        from holding_account import snapshot,restore
        need(material['schema']=='research.fixed-share-reconciliation-checkpoint/1'
             and material['arm']==self.arm and material['source_sha256']==self.identity,'CHECKPOINT_ARM_SOURCE_CONTEXT')
        need(material['checkpoint_sha256']==expected_sha256 and digest({k:v for k,v in material.items() if k!='checkpoint_sha256'})==expected_sha256,
             'CHECKPOINT_WRAPPER_HASH')
        need(material['previous_checkpoint_sha256']==expected_predecessor
             and material['event_prefix']==event_prefix
             and material['pending']['source_state_sha256']==expected_source_state,'CHECKPOINT_PREDECESSOR_SOURCE_PREFIX')
        self.account=restore(material['account'],self.identity)
        need(snapshot(self.account)==material['account'],'CHECKPOINT_ACCOUNT_ROUNDTRIP')
        self.pending=material['pending'];self.previous_state=material['previous_state'];self.previous_plan=material['previous_plan'];self.previous_projection=material['previous_projection']
        self.last_nav=F(material['last_nav']);self.fees=F(material['cumulative_fees']);self.traded=F(material['cumulative_traded_notional'])
        self.checkpoint_chain=expected_sha256


def synthetic_tests():
    """Actual financial/canonical tests, credential-free hosted container only."""
    hosted()
    import ast
    import inspect
    from sentinel.execution import held_targets
    from sentinel.execution.projection import project
    from sentinel.execution.target_reprojection import TargetProjectionRefused
    from sentinel.execution.numeric import exact_decimal
    from sentinel.core.decision import ShadowTarget
    from holding_account import Account,Intent,RawOpen,trade,accrue,pay,snapshot,restore
    checks=[]
    def test(name,condition):
        need(condition,'SYNTHETIC_'+name);checks.append(name)
    def refuses(name,call):
        try:call()
        except (ValueError,TypeError,AssertionError,TargetProjectionRefused):checks.append(name);return
        raise ValueError('SYNTHETIC_DID_NOT_REFUSE_'+name)
    ep=dict(slot_id=1,current_shares=132,security_id='A',signal_date='2017-01-03')
    before=NS(wealth_core={'episodes':{'1':ep}},pending=[],last_processed_session='2018-01-02')
    after=NS(wealth_core={'episodes':{'1':dict(ep)}},pending=[],last_processed_session='2018-01-03')
    previous=NS(target_exposure=D('.55'),decision_session=date(2018,1,2),target_basket={'A':D(72),BIL:D(10)},opening_intents=())
    prior=NS(target_basket=previous.target_basket,through_session=date(2018,1,3),opening_sizing=None,action_multipliers={},action_evidence=())
    carried=held_targets.carry_quantities(previous=previous,previous_state=before,projection=prior,state=after,exposure=D('.55'))
    test('CONTINUING_INTENT_AND_BIL_CARRY',carried==previous.target_basket)
    raw=project(shadow_weights={'A':D(1)},exposure=D('.55'),nav=D(13000),marks={'A':D(100)},defensive_security=BIL,defensive_weight=D('.45'))
    canonical=ShadowTarget(shares={'A':D(132)},tickers={'A':'A'})
    final=held_targets.apply(raw,targets={'A':D(72)},canonical_target=canonical,marks={'A':D(100)})
    test('72_TO_71_NAV_DRIFT_RETAINED',raw.quantities['A']==71 and final.quantities['A']==72)
    test('EXACT_FINITE_FRACTION_DECIMAL',exact_decimal(F(1,5))==D('.2'))
    test('EXPOSURE_CHANGE_CLEARS_CARRY',held_targets.carry_quantities(previous=previous,previous_state=before,projection=prior,state=after,exposure=D('.35'))=={})
    replacement=NS(wealth_core={'episodes':{'1':{**ep,'signal_date':'2018-01-03'}}},pending=[],last_processed_session='2018-01-03')
    test('NEW_EPISODE_DOES_NOT_INHERIT', 'A' not in held_targets.carry_quantities(previous=previous,previous_state=before,projection=prior,state=replacement,exposure=D('.55')))
    refuses('EXIT_CANNOT_BE_RESURRECTED',lambda:held_targets.apply(raw,targets={'A':D(72)},canonical_target=ShadowTarget(shares={},tickers={}),marks={'A':D(100)}))
    augmented=replace(raw,quantities={'A':D(71),'N':D(1)},notional={'A':D(7100),'N':D(100)})
    limited=held_targets.apply(augmented,targets={'A':D(72)},canonical_target=ShadowTarget(shares={'A':D(132),'N':D(1)},tickers={}),marks={'A':D(100),'N':D(100)})
    test('OVERWEIGHT_PRESERVED_NEW_HEADROOM_ZERO',limited.quantities['A']==72 and limited.quantities['N']==0)
    # Deliberately broken seams must fail the very same invariant, not merely
    # record that a valid original example passes.
    refuses('REMOVED_APPLY_MUTANT_DETECTED',lambda:test('MUTANT_RETAINED_QUANTITY',raw.quantities['A']==72))
    tree=ast.parse(inspect.getsource(held_targets.carry_quantities))
    guard=next(n for n in tree.body[0].body if isinstance(n,ast.If) and 'previous.target_exposure' in ast.unparse(n.test))
    guard.test=ast.Constant(False);ast.fix_missing_locations(tree)
    namespace={};exec(compile(tree,'<hosted-exposure-guard-falsifier>','exec'),vars(held_targets),namespace)
    mutant=namespace['carry_quantities'](previous=previous,previous_state=before,projection=prior,state=after,exposure=D('.35'))
    refuses('REMOVED_EXPOSURE_GUARD_MUTANT_DETECTED',lambda:test('MUTANT_EXPOSURE_CHANGE',mutant=={}))
    source='1'*64;account=Account(source_sha256=source,cash='100')
    intent=Intent(event_id='BUY',signal_session='2018-01-02',execution_session='2018-01-03',episode='E',security_id='A',ticker='A',side='BUY',shares=20)
    quote=RawOpen(session='2018-01-03',security_id='A',price='10')
    funded,event=trade(account,intent,quote)
    test('FEE_INCLUSIVE_WHOLE_BUY_CLIPPING',funded.positions['E'].shares==9 and funded.cash==F('9.91') and intent.shares==20)
    refuses('NO_PRE_ENTRY_DIVIDEND_ENTITLEMENT',lambda:accrue(account,event_id='EX0',session='2018-01-03',claim_id='C0',security_id='A',cash_per_share='1',pay_session='2018-01-04'))
    claimed,_=accrue(funded,event_id='EX',session='2018-01-04',claim_id='C',security_id='A',cash_per_share='1',pay_session='2018-01-08')
    test('CLAIM_NOT_SPENDABLE_EARLY',claimed.cash==funded.cash and claimed.claims['C'].amount==9)
    refuses('EARLY_CLAIM_PAYMENT',lambda:pay(claimed,event_id='EARLY',session='2018-01-05',claim_id='C'))
    paid,_=pay(claimed,event_id='PAY',session='2018-01-08',claim_id='C')
    refuses('DUPLICATE_CLAIM_PAYMENT',lambda:pay(paid,event_id='PAY2',session='2018-01-09',claim_id='C'))
    refuses('NEGATIVE_CASH',lambda:Account(source_sha256=source,cash='-1'))
    cp=snapshot(paid);restored=restore(cp,source)
    test('ACCOUNT_CHECKPOINT_CONTINUATION',snapshot(restored)==cp)
    corrupt=deepcopy(cp);corrupt['state']['cash']='999'
    refuses('CORRUPTED_CHECKPOINT',lambda:restore(corrupt,source))
    refuses('CHANGED_SOURCE_CHECKPOINT',lambda:restore(cp,'2'*64))
    refuses('SAME_CLOSE_FILL',lambda:Intent(event_id='X',signal_session='2018-01-03',execution_session='2018-01-03',episode='E',security_id='A',ticker='A',side='BUY',shares=1))
    refuses('FUTURE_RAW_QUOTE_REFUSED',lambda:trade(account,intent,RawOpen(session='2018-01-04',security_id='A',price='1')))
    refuses('UNDECLARED_PROJECTION_ARGUMENT_API_SHAPE_ONLY',lambda:project(shadow_weights={'A':D(1)},exposure=D(1),nav=D(100),marks={'A':D(10)},future_close=D(1000)))
    fake=NS(prefix=lambda:dict(records=0,bytes=0,sha256='0'*64))
    q=ShareArm('Q',digest(dict(study=source,arm='Q')),fake)
    p=ShareArm('P',digest(dict(study=source,arm='P')),fake)
    q.pending=dict(source_state_sha256='3'*64)
    checkpoint=q.checkpoint()
    refuses('CROSS_ARM_CHECKPOINT',lambda:p.restore_checkpoint(checkpoint,expected_sha256=checkpoint['checkpoint_sha256'],
        expected_predecessor='0'*64,expected_source_state='3'*64,event_prefix=fake.prefix()))
    refuses('CHANGED_CHECKPOINT_PREDECESSOR',lambda:q.restore_checkpoint(checkpoint,expected_sha256=checkpoint['checkpoint_sha256'],
        expected_predecessor='4'*64,expected_source_state='3'*64,event_prefix=fake.prefix()))
    return dict(status='PASS',actual_hosted_financial_calls=True,checks=checks,guard_mutants_detected=['removed_apply','removed_exposure_guard'],canonical_source_sha256=file_sha(Path(held_targets.__file__)),no_strategy_steps=True)


def run(args):
    hosted();paths(args)
    input_proof=verify_inputs(args)
    rows,events,source=load_source(args.p00)
    bil,bars,bil_actions,bil_proof=bil_input(args.input,[r['session'] for r in rows])
    need(not args.output.exists(),'OUTPUT_MUST_BE_NEW');args.output.mkdir(parents=True)
    synthetic=synthetic_tests();write(args.output/'synthetic-proof.json',synthetic)
    command=[sys.executable,str(Path(__file__).resolve()),'--mode','scalar','--source',str(args.source),'--legacy',str(args.legacy),
             '--current',str(args.current),'--p00',str(args.p00),'--input',str(args.input),'--output',str(args.output/'scalar')]
    subprocess.run(command,check=True,env=dict(os.environ),timeout=600)
    scalar_rows={a:records(args.output/'scalar'/(a+'.jsonl.gz')) for a in ('S','A')}
    need(all(len(v)==COUNT for v in scalar_rows.values()),'BOTH_SCALAR_ARMS_COMPLETE')
    from holding_account import snapshot,state,mark
    from sentinel.execution import projection,held_targets
    need(str(projection.__file__).startswith('/current/') and str(held_targets.__file__).startswith('/current/'), 'EXACT_CURRENT_CANONICAL_NAMESPACE')
    source_files={}
    for root,labels in [(args.current,('sentinel/execution/projection.py','sentinel/execution/held_targets.py','sentinel/core/decision.py','shared/stock_strategy_shared/wealth_core/v5.py')),
                        (args.legacy,('research/capital_risk/holding_account.py','research/capital_risk/holding_actions.py'))]:
        for name in labels:source_files[str(root/name)]=file_sha(root/name)
    identity=digest(dict(source=source,bil=bil_proof,files=source_files,worker_sha256=file_sha(Path(__file__)),
                         input_manifest_sha256=input_proof['manifest_sha256'],protocol_sha256=input_proof['protocol_sha256']))
    event_journal=Journal(args.output/'events.jsonl.gz');daily=Journal(args.output/'daily.jsonl.gz')
    trace=Journal(args.output/'source-trace.jsonl.gz');checkpoints=Journal(args.output/'checkpoints.jsonl.gz')
    account_identities={a:digest(dict(study_identity=identity,arm=a)) for a in ('Q','P')}
    arms={a:ShareArm(a,account_identities[a],event_journal) for a in ('Q','P')};navs={a:[] for a in ('S','A','Q','P')}
    by_day={}
    for e in events:by_day.setdefault(e['session'],[]).append(e)
    previous_ownership=previous_target=None
    try:
        for index,row in enumerate(rows):
            day=row['session'];audit=row['evidence']['research_entry_audit'];opening=audit['opening_accounting'];closing=audit['closing_accounting']
            opens={s:str(p['raw_price']) for s,p in opening['prices'].items() if p['status']=='RAW_OPEN'}
            closes={s:str(p['raw_price']) for s,p in closing['prices'].items() if p['status']=='CURRENT'}
            opens[BIL]=str(bars[day]['raw_open']);closes[BIL]=str(bars[day]['raw_close'])
            src_events=by_day.get(day,[])
            for event in src_events:
                if event['event_type']=='BUY':
                    sid=event['security_id'];price=str(event['price'])
                    need(event['session']==day and D(price).is_finite() and D(price)>0,'VALID_SAME_OPEN_SOURCE_BUY_QUOTE')
                    need(sid not in opens or F(opens[sid])==F(price),'SOURCE_BUY_QUOTE_CONFLICT')
                    opens[sid]=price
            trace.add(dict(session=day,original_row=row,source_record_sha256=digest(row),source_events=src_events,
                           prices=dict(raw_open=opens,raw_close=closes),bil_bar=bars[day],bil_actions=[a for a in bil_actions if a.get('ex_date')==day or a.get('payable_date')==day]))
            record=dict(schema='research.fixed-share-reconciliation-day/1',session=day,source_state_sha256=row['state_sha256'],
                        source_input_sha256=row['input_sha256'],source_chain_sha256=row['chain_sha256'],decision_sha256=digest(row['decision']),
                        close_target=str(row['decision']['target_core_exposure']),arms={a:scalar_rows[a][index] for a in ('S','A')})
            for a in ('S','A'):navs[a].append((day,record['arms'][a]['economics']['strategy_nav']))
            for a,arm in arms.items():
                execution=None
                if index:
                    execution=arm.open(row,src_events,events,bars,bil_actions,opens)
                else:
                    need(not arm.account.positions and not arm.account.claims,'FLAT_UNFUNDED_FIRST_CLOSE')
                next_day=rows[index+1]['session'] if index+1<len(rows) else None
                pending,projection_audit,nav,sizing=arm.close_plan(row,next_day,closes)
                record['arms'][a]=dict(nav=str(nav),sizing_nav=str(sizing),cash=str(arm.account.cash),claims_value=str(nav-sizing),
                                       previous_nav=str(arm.last_nav),net_factor=str(nav/arm.last_nav),snapshot=snapshot(arm.account),
                                       marks=closes,execution=execution,pending=pending,projection_audit=projection_audit,
                                       cumulative_fees=str(arm.fees),cumulative_traded_notional=str(arm.traded),
                                       holdings=[dict(episode=p.episode,security_id=p.security_id,ticker=p.ticker,kind=p.kind,shares=str(p.shares),
                                                      raw_close=closes[p.security_id],value=str(p.shares*F(closes[p.security_id]))) for p in arm.account.positions.values()])
                need(arm.account.cash>=0 and nav>0,'POSITIVE_UNLEVERED_ACCOUNT')
                arm.last_nav=nav;navs[a].append((day,str(nav)))
            daily.add(record)
            own=record['arms']['P']['pending']['ownership'];target=record['close_target']
            boundary=(index==len(rows)-1 or day[:7] != rows[index+1]['session'][:7] or own!=previous_ownership or target!=previous_target)
            if boundary:
                for a,arm in arms.items():checkpoints.add(dict(session=day,checkpoint=arm.checkpoint(),daily_prefix=daily.prefix(),source_state_sha256=row['state_sha256']))
            previous_ownership,previous_target=own,target
        commitments=dict(events=event_journal.close(),daily=daily.close(),trace=trace.close(),checkpoints=checkpoints.close())
    except BaseException:
        for j in (event_journal,daily,trace,checkpoints):
            try:j.close()
            except Exception:pass
        raise
    summaries={}
    for a,series in navs.items():
        values=[F(v) for _,v in series];high=values[0];peak=series[0][0];worst=F(0);worst_peak=worst_trough=peak
        for (day,_),value in zip(series,values):
            if value>=high:high=value;peak=day
            dd=1-value/high
            if dd>worst:worst=dd;worst_peak=peak;worst_trough=day
        summaries[a]=dict(first=START,last=END,closes=COUNT,start_nav='50000',end_nav=str(values[-1]),return_fraction=str(values[-1]/50000-1),
                          maximum_drawdown=str(worst),drawdown_peak=worst_peak,drawdown_trough=worst_trough)
        if a in arms:summaries[a].update(fees=str(arms[a].fees),traded_notional=str(arms[a].traded),restores=arms[a].restore_count)
    write(args.output/'summary.json',dict(status='COMPLETE_REVIEW_REQUIRED',arms=summaries,attribution=['S_TO_A_DEFENSIVE_SOURCE','A_TO_Q_ACCOUNT_GEOMETRY_AND_CONVENTIONS','Q_TO_P_PERSISTENCE'],performance_admitted=False))
    write(args.output/'worker-proof.json',dict(schema='research.fixed-share-reconciliation-proof/1',status='COMPLETE_REVIEW_REQUIRED',source=source,
        source_files=source_files,worker_sha256=file_sha(Path(__file__)),bil=bil_proof,identity=identity,journals=commitments,
        initial_accounts={a:arm.initial for a,arm in arms.items()},account_identities=account_identities,
        canonical_import_paths=dict(projection=projection.__file__,held_targets=held_targets.__file__),
        closes=COUNT,Core_steps=0,Sentinel_steps=0,full_SessionState_claim=False,protected_fill_claim=False,performance_admitted=False,
        input=input_proof,synthetic_tests=synthetic,scalar_proof=json.loads((args.output/'scalar/proof.json').read_bytes())))
    print(json.dumps(dict(status='COMPLETE_REVIEW_REQUIRED',closes=COUNT,arms=['S','A','Q','P'],performance_admitted=False)),flush=True)


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','legacy','current','p00','input','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--mode',choices=('run','scalar'),default='run')
    args=parser.parse_args();hosted()
    (scalar if args.mode=='scalar' else run)(args)


if __name__=='__main__':main()
