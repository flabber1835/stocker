"""Read-only binding of committed observations to permanent episode identities.

No Core transition, signal calculation, hypothetical trade or funded NAV is run.
"""
from collections import defaultdict
from decimal import Decimal as D
import gzip,hashlib,json,time
from pathlib import Path

def need(value,code):
    if not value:raise ValueError(code)
def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def bind_observations(row,episodes,*,row_index):
    holdings=row['evidence']['breadth']['holdings']
    operations=sorted((o for o in row['evidence']['research_entry_audit']['operations']
        if o['operation'] in ('HOLD_UNCHANGED','CLOSE_POSITION')),key=lambda o:o['slot_id'])
    need(len(holdings)==len(operations)==len(episodes),'REFUSED_IDENTITY_SLOT_COVERAGE')
    result=[]
    for observed,operation in zip(holdings,operations):
        slot=operation['slot_id'];need(slot in episodes,'REFUSED_IDENTITY_SLOT')
        ep=episodes[slot]
        need(ep['security_id']==operation['security_id'],'REFUSED_PERMANENT_IDENTITY')
        need(observed['ticker']==operation['ticker'],'REFUSED_TICKER_CORROBORATION')
        age=row_index-ep['entry_index']
        need(age==observed['age_sessions'] and operation['detail'].get('age',age)==age,'REFUSED_EPISODE_AGE_'+json.dumps(dict(session=row['session'],slot=slot,derived_age=age,operation=operation,observed=observed)))
        result.append(dict(slot_id=slot,security_id=ep['security_id'],signal_session=ep['signal_session'],
            episode=ep['signal_session']+'/'+str(slot),shares=str(ep['shares']),
            source_observation=observed,source_state_sha256=row['state_sha256'],
            source_input_sha256=row['input_sha256'],source_chain_sha256=row['chain_sha256']))
    return result

def bind_book(root,output,*,review_path=None):
    started=time.perf_counter();root=Path(root);output=Path(output)
    cpraw=(root/'checkpoint.json.gz').read_bytes();cp=json.loads(gzip.decompress(cpraw))
    review=json.loads((root/'fixed-review.json' if review_path is None else Path(review_path)).read_bytes())
    need(review['final_file_sha256']==hashlib.sha256(cpraw).hexdigest() and review['final_outer']==cp['sha256']
        and review['journal_commitments']==cp['journals'] and review['full_chain_verified']
        and review['canonical_roundtrip'],'REFUSED_ORIGINAL_CP_BINDING')
    rows=[]
    for name,count in (('formation',126),('daily',4639)):
        raw=(root/(name+'.jsonl')).read_bytes();lines=raw.splitlines(keepends=True);spec=cp['journals'][name]
        need(len(lines)==count and len(raw)==spec['bytes'] and hashlib.sha256(raw).hexdigest()==spec['prefix_sha256']
            and hashlib.sha256(lines[-1]).hexdigest()==spec['last_record_sha256'],'REFUSED_IDENTITY_ORIGINAL_PREFIX')
        rows.extend(json.loads(line) for line in lines)
    byday=defaultdict(list)
    for event in cp['run']['state']['ledger']['events']:byday[event['session']].append(event)
    event_days=sorted(byday);cursor=0;episodes={};aggregate=defaultdict(D);last=None
    chain='0'*64;records=0;duplicate_closes=0;observations=0;max_error=D(0);conversions=0
    origins=set();snapshot_rows=[];output.mkdir(exist_ok=False)
    with (output/'identity-bindings.jsonl').open('xb') as stream:
        for row_index,row in enumerate(rows):
            day=row['session'];need(last is None or last<day,'REFUSED_IDENTITY_AXIS')
            current={o['slot_id']:o for o in row['evidence']['research_entry_audit']['operations']
                if o['operation'] in ('HOLD_UNCHANGED','CLOSE_POSITION')}
            need(len(current)==len([o for o in row['evidence']['research_entry_audit']['operations']
                if o['operation'] in ('HOLD_UNCHANGED','CLOSE_POSITION')]),'REFUSED_DUPLICATE_SLOT')
            split_used=set()
            while cursor<len(event_days) and event_days[cursor]<=day:
                for event in byday[event_days[cursor]]:
                    sid=event['security_id'];kind=event['event_type'];detail=event['detail']
                    if kind=='SPLIT':
                        matches=[slot for slot,e in sorted(episodes.items()) if e['security_id']==sid
                            and (event_days[cursor],slot) not in split_used and abs(e['shares']-D(str(detail['before'])))<=D('1e-9')]
                        need(bool(matches),'REFUSED_SPLIT_EPISODE_BINDING');slot=matches[0]
                        # Canonical split traversal is by ascending slot; preserve its per-lot events.
                        episodes[slot]['shares']=D(str(detail['after']));split_used.add((event_days[cursor],slot))
                    elif kind=='CONVERSION':
                        matches=[slot for slot,e in episodes.items() if e['security_id']==sid]
                        need(len(matches)==1,'REFUSED_AMBIGUOUS_CONVERSION_LOTS')
                        slot=matches[0];need(abs(episodes[slot]['shares']-D(str(detail['shares_in'])))<=D('1e-9'),'REFUSED_CONVERSION_SOURCE_QUANTITY')
                        episodes[slot].update(security_id=detail['delivered_security_id'],shares=D(str(detail['shares_delivered'])))
                        conversions+=1
                    elif kind=='CASH_MERGER':
                        episodes={k:e for k,e in episodes.items() if e['security_id']!=sid}
                    if kind=='CONVERSION':
                        aggregate[sid]-=D(str(detail['shares_in']));aggregate[detail['delivered_security_id']]+=D(str(detail['shares_delivered']))
                    else:aggregate[sid]+=D(str(event['shares_delta']))
                cursor+=1
            for fill in row['retry_diagnostics']['events']:
                if fill['outcome']!='FILLED':continue
                slot=fill['slot_id'];need(slot not in episodes,'REFUSED_OPEN_OVER_OWNED_EPISODE')
                need(slot in current and fill['session']==day and fill['signal_session']<day,'REFUSED_FILLED_EPISODE_TIME')
                sid=fill.get('filled_security_id') or fill['security_id']
                need(sid==current[slot]['security_id'],'REFUSED_FILLED_SECURITY_IDENTITY')
                episodes[slot]=dict(security_id=sid,shares=D(str(fill['filled_shares'])),signal_session=fill['signal_session'],entry_index=row_index)
                origins.add((slot,fill['signal_session']))
            episodes={slot:ep for slot,ep in episodes.items() if slot in current}
            bound=bind_observations(row,episodes,row_index=row_index);observations+=len(bound)
            per_sid=defaultdict(D)
            for ep in episodes.values():per_sid[ep['security_id']]+=ep['shares']
            for sid in set(per_sid)|set(aggregate):
                error=abs(per_sid.get(sid,D(0))-aggregate[sid]);need(error<=D('1e-8'),'REFUSED_IDENTITY_QUANTITY_RECONCILIATION')
                max_error=max(max_error,error)
            if len(per_sid)<len(episodes):duplicate_closes+=1
            record=dict(session=day,phase=row['phase'],holdings=bound,
                source_state_sha256=row['state_sha256'],source_input_sha256=row['input_sha256'],source_chain_sha256=row['chain_sha256'])
            chain=hashlib.sha256(encoded(dict(previous=chain,record=record))).hexdigest()
            stream.write(encoded({**record,'identity_chain_sha256':chain})+b'\n');records+=1;last=day
    final=cp['run']['state']['wealth_core']['episodes']
    need(set(map(str,episodes))==set(final),'REFUSED_FINAL_EPISODE_SET')
    for slot,ep in episodes.items():
        actual=final[str(slot)]
        need(ep['security_id']==actual['security_id'] and ep['signal_session']==actual['signal_date']
            and abs(ep['shares']-D(str(actual['current_shares'])))<=D('1e-9'),'REFUSED_FINAL_EPISODE_STATE')
    need(records==4765 and last=='2026-07-31' and cursor==len(event_days),'REFUSED_IDENTITY_COMPLETION')
    result=dict(schema='research.holding-identity-qualification/1',status='IDENTITY_BINDING_PASSED',records=records,
        formation_records=126,measured_records=4639,holding_observations=observations,origins=len(origins),
        duplicate_security_closes=duplicate_closes,conversions=conversions,max_aggregate_quantity_residual=str(max_error),
        all_observations_bound_by_source_slot_order=True,ticker_only_join=False,final_episode_state_matched=True,
        identity_chain_sha256=chain,identity_file_sha256=sha(output/'identity-bindings.jsonl'),
        canonical_strategy_transitions_executed=0,hypothetical_financial_accounts_executed=0,
        raw_mark_or_selective_weight_coverage_qualified=False,processing_seconds=time.perf_counter()-started)
    (output/'summary.json').write_bytes(encoded(result)+b'\n');return result
