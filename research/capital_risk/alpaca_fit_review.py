"""Independent stopped Core trace review; never advances Core or an account."""
from __future__ import annotations
import argparse
from collections import defaultdict
from dataclasses import asdict
from fractions import Fraction as Q
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from alpaca_fit_inputs import hosted,need,responses
from alpaca_fit_baseline import encoded,source_check,save
from alpaca_fit_policy import profiles,leaf


def close(a,b):
    a,b=float(a),float(b)
    return abs(a-b)<=max(1e-8,1e-10*max(abs(a),abs(b)))


def raw_nav(cash,shares,prices,claims):
    return cash+sum(q*prices[sid] for sid,q in shares.items())+sum(claims.values())


def review(evidence,inputs,prefix_inputs,request,output):
    hosted();root=Path(evidence);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    from sentinel.core.session import SessionState
    from sentinel.core.formation import Formation,FormationPlan
    from sentinel.feed import calendar
    binding=source_check(Path('/src'),request['source_files'])
    protocol=json.loads(Path('/src/research/capital_risk/alpaca-fit-protocol.json').read_bytes())
    plan_record=json.loads((root/'plan.json').read_bytes());plan=FormationPlan.model_validate(plan_record['plan'])
    retained=json.loads((root/'retained-checkpoints.json').read_bytes())
    status=json.loads((root/'baseline-status.json').read_bytes())
    need(status['source_sha256']==binding and retained,'REVIEW_SOURCE_OR_NO_ORIGIN')
    origin_binding=plan.source_sha256;inherited={}
    interpretation=request['dataset_sha256'];repair=None;repair_events={};repair_records={}
    role=None;role_events={};role_records={}
    if request.get('source_role_repair'):
        from alpaca_fit_identity_repair import digest,predecessor
        role_spec=request['source_role_repair'];path=Path('/src')/role_spec['path']
        need(path.stat().st_size==role_spec['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==role_spec['sha256'],'REVIEW_ROLE_SOURCE')
        role=json.loads(path.read_bytes());role_fact=json.loads((root/'source-role-input-admission.json').read_bytes())
        from alpaca_fit_merger_roles import all_events
        role_events={e['record_sha256']:e for e in all_events(role)}
        need(predecessor(root,role,request['continuation'])==role_fact['predecessor'],'REVIEW_ROLE_OWN_ANCHOR')
    if request.get('sparse_input_repair'):
        from alpaca_fit_identity_repair import digest,predecessor
        spec=request['sparse_input_repair'];path=Path('/src')/spec['path']
        need(path.stat().st_size==spec['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==spec['sha256'],'REVIEW_REPAIR_SOURCE')
        repair=json.loads(path.read_bytes());fact=json.loads((root/'factual-input-admission.json').read_bytes())
        events=(repair['legacy_events']+repair['events']) if repair['schema'].endswith('/2') else [repair]
        repair_events={e['record_sha256']:e for e in events}
        need(len(repair_events)==len(events),'REVIEW_DISTINCT_FACT_REGISTRY')
        exact=predecessor(root,repair,request['continuation'])
        need(exact==fact['predecessor'],'REVIEW_ALL_FACTUAL_OWN_ANCHORS')
        basis=repair['predecessor'];anchor=root/basis['checkpoint']['file']
        need(anchor.stat().st_size==basis['checkpoint']['bytes'] and hashlib.sha256(anchor.read_bytes()).hexdigest()==basis['checkpoint']['sha256'],
             'REVIEW_FACTUAL_ANCHOR_FILE')
        original=json.loads(gzip.decompress(anchor.read_bytes()))
        need(original['canonical']['sha256']==basis['inner_sha256']
             and original['canonical']['state_sha256']==basis['state_sha256']
             and original['canonical']['plan']['source_sha256']==origin_binding,'REVIEW_FACTUAL_ANCHOR_CONTENT')
        interpretation=digest({'dataset_sha256':request['dataset_sha256'],'factual_interpretation_sha256':digest(repair)})
        if role:interpretation=digest({'source_interpretation_sha256':interpretation,'source_role_descriptor_sha256':digest(role)})
        if request.get('admission_context'):
            interpretation=digest({'source_interpretation_sha256':interpretation,'admission_context':request['admission_context']})
        need(fact['facts']['descriptor_sha256']==digest(repair) and fact['descriptor_file_sha256']==spec['sha256']
             and fact['input_interpretation_sha256']==interpretation and fact['facts']['record_sha256']==repair['record_sha256']
             and fact['facts']['provider_rows_or_financial_state_modified'] is False,'REVIEW_FACTUAL_ADMISSION')
    if role and repair is None:interpretation=digest({'source_interpretation_sha256':interpretation,'source_role_descriptor_sha256':digest(role)})
    if request.get('admission_context'):
        from alpaca_fit_inputs import SPLIT_CONTEXT
        from sentinel.feed.rolling_contract import digest as input_digest
        need(request['admission_context']==SPLIT_CONTEXT,'REVIEW_CONTEXT_POLICY')
        if repair is None:interpretation=input_digest({'source_interpretation_sha256':interpretation,'admission_context':SPLIT_CONTEXT})
        context=json.loads((root/'input-context-admission.json').read_bytes())
        need(context=={'policy':SPLIT_CONTEXT,'input_interpretation_sha256':interpretation,'core_feature_sessions':300,
             'maximum_extra_source_predecessors':1,'inferred_rows':0},'REVIEW_CONTEXT_INTERPRETATION')
    if role:
        need(role_fact['descriptor_file_sha256']==role_spec['sha256'] and role_fact['input_interpretation_sha256']==interpretation
             and role_fact['facts']['descriptor_sha256']==digest(role)
             and role_fact['facts']['records_sha256']==role['records_sha256']
             and role_fact['facts']['provider_rows_or_financial_state_modified'] is False,'REVIEW_ROLE_ADMISSION')
    if request.get('continuation'):
        spec=request['continuation'];lineage=root/'lineage'
        previous_plan=json.loads((lineage/'previous-plan.json').read_bytes())
        need(previous_plan['plan']==plan_record['plan'] and previous_plan['measured_axis']==plan_record['measured_axis'],
             'ORIGINAL_FORMATION_PLAN_UNCHANGED')
        previous_source=json.loads((lineage/'previous-source-bindings.json').read_bytes())
        protected=[p for p in previous_source if p.startswith(('sentinel/','shared/stock_strategy_shared/'))
            or p in ('research/capital_risk/alpaca_fit_policy.py','research/capital_risk/alpaca-fit-protocol.json')]
        need(all(previous_source[p]==request['source_files'][p] for p in protected),'UNCHANGED_FINANCIAL_SOURCE')
        admission=json.loads((lineage/'admission.json').read_bytes())
        predecessor=lineage/'exact-predecessor.json.gz'
        need(admission['checkpoint']==spec['checkpoint'] and admission['journal']==spec['checkpoint']['journal']
             and predecessor.stat().st_size==spec['checkpoint']['bytes']
             and hashlib.sha256(predecessor.read_bytes()).hexdigest()==spec['checkpoint']['sha256'],
             'EXACT_PREDECESSOR_PRESERVED')
        tail=admission['recovered_tail'];tail_path=lineage/tail['file']
        need(tail_path.stat().st_size==tail['bytes'] and hashlib.sha256(tail_path.read_bytes()).hexdigest()==tail['sha256'],
             'RECOVERED_TAIL_PRESERVED')
        inherited={r['file']:r for r in json.loads((lineage/'previous-retained-checkpoints.json').read_bytes())}
        equality=json.loads((root/'packed-input-equivalence.json').read_bytes())
        need(equality['prior_state_sha256']==spec['checkpoint']['state_sha256']
             and equality['reference_input_sha256']==equality['packed_input_sha256']
             and equality['complete_published_input_equal'] is True,'PACKED_INPUT_EQUIVALENCE')
    need(plan_record['source_sha256']==origin_binding and status.get('origin_source_sha256',origin_binding)==origin_binding,
         'ORIGINAL_SOURCE_IDENTITY')
    profiles_,baseline=profiles(protocol);source=Path('/src/sentinel/controller/owned_impairment.py')
    sha=hashlib.sha256(source.read_bytes()).hexdigest();leaves={p.id:leaf(source,p,sha) for p in profiles_}
    leaf_states={key:m.fresh() for key,m in leaves.items()}
    frames=[];prefixes={};chain='0'*64;rolling=hashlib.sha256();length=0
    with (root/'canonical.jsonl').open('rb') as f:
        for line in f:
            row=json.loads(line);need(encoded(row)==line and row['previous_chain_sha256']==chain,'JOURNAL_FRAME_OR_CHAIN')
            chain=hashlib.sha256(line).hexdigest();rolling.update(line);length+=len(line)
            frames.append(row);prefixes[length]=(rolling.hexdigest(),len(frames),chain)
    commitment=status['journal']
    need((length,rolling.hexdigest(),len(frames),chain)==(commitment['bytes'],commitment['sha256'],commitment['records'],commitment['chain_sha256']),'CURRENT_JOURNAL_COMMITMENT')
    need(frames[0]['phase']=='WARMUP_ORIGIN' and frames[0]['session'] is None,'ORIGIN_FRAME')
    source_sids={e['security_id'] for row in frames[1:] for e in row['wealth_core']['episodes'].values()}
    source_sids.update(s for row in frames[1:] for s in row['prices'])
    classified=json.loads((Path(prefix_inputs)/'capture/classification.json').read_bytes())
    ticker_to_sid={r['ticker']:r['asset_id'] for r in classified['selected']}
    selected_tickers={t for t,s in ticker_to_sid.items() if s in source_sids};raw_prices={};spy={}
    from sentinel.feed.alpaca_observation import bar_page_rows
    axis=set(calendar.sessions_in_range(protocol['data_start'],protocol['data_end']))
    from itertools import chain
    for proof,reply in chain(responses(Path(prefix_inputs)),responses(Path(inputs))):
        params=proof.get('params') or {}
        if repair and proof['endpoint'].endswith('/corporate-actions'):
            for record in reply['corporate_actions'].get('name_changes',[]):
                key=digest(record)
                if key not in repair_events:continue
                expected=repair_events[key]
                if proof['file']!=expected['response_file']:continue
                need(proof['file']==expected['response_file'] and proof['raw_sha256']==expected['raw_response_sha256']
                     and proof['sha256']==expected['compressed_response_sha256'],'REVIEW_EXACT_NAME_RESPONSE')
                need(record['old_cusip']==record['new_cusip']
                     and (record['old_symbol']!=record['new_symbol'] or expected['kind']=='UNCHANGED_CUSIP_NAME_EVENT')
                     and record['process_date']==expected['effective_session'],'REVIEW_NAME_ONLY_FACT')
                sid=ticker_to_sid[record['new_symbol']]
                need(hashlib.sha256(sid.encode()).hexdigest()==expected['permanent_id_sha256'],'REVIEW_NAME_SID')
                repair_records[key]=repair_records.get(key,0)+1
        if role and proof['endpoint'].endswith('/corporate-actions'):
            for record in reply['corporate_actions'].get('stock_mergers',[])+reply['corporate_actions'].get('cash_mergers',[]):
                key=digest(record)
                if key not in role_events:continue
                expected=role_events[key]
                if proof['file']!=expected['response_file']:continue
                need(proof['raw_sha256']==expected['raw_response_sha256'] and proof['sha256']==expected['compressed_response_sha256']
                     and record['acquirer_symbol']!=record['acquiree_symbol']
                     and record['acquirer_cusip']!=record['acquiree_cusip']
                     and record['effective_date']==expected['effective_session'],'REVIEW_RECIPIENT_ROLE_FACT')
                sid=ticker_to_sid[record['acquirer_symbol']]
                need(hashlib.sha256(sid.encode()).hexdigest()==expected['permanent_id_sha256'],'REVIEW_RECIPIENT_ID')
                role_records[key]=role_records.get(key,0)+1
        if not proof['endpoint'].endswith('/bars'):continue
        if params.get('adjustment')=='all' and 'SPY' in reply.get('bars',{}):
            for (_,day),bar in bar_page_rows({'SPY':reply['bars']['SPY']},symbols={'SPY'},sessions=axis).items():
                need(day not in spy,'SPY_REVIEW_DUPLICATE');spy[day]=bar
        if params.get('adjustment')!='raw':continue
        selected={t:rows for t,rows in reply['bars'].items() if t in selected_tickers}
        for (ticker,day),bar in bar_page_rows(selected,symbols=selected_tickers,sessions=axis).items():
            key=(ticker_to_sid[ticker],day);need(key not in raw_prices,'RAW_REVIEW_DUPLICATE');raw_prices[key]=bar
    origin=json.loads(gzip.decompress((root/'warmup-origin.json.gz').read_bytes()))
    canonical=Formation.resume(origin['canonical'],plan=plan).state
    need(canonical.state_hash==frames[0]['state_sha256'],'ORIGIN_CANONICAL_STATE')
    cash=canonical.wealth_core['cash'];shares=defaultdict(float);claims={};events=[];by_session={None:frames[0]};prior=canonical.state_hash
    formation_count=measured_count=0;checked_prices=0;last=None
    for row in frames[1:]:
        day=row['session'];need(row['prior_state_sha256']==prior,'STATE_CHAIN')
        if last:need(day==calendar.next_session(last),'DAILY_AXIS')
        else:need(day==plan.axis[299],'FIRST_FORMATION_SESSION')
        need(Q(str(row['spy_close_adjusted']))==Q(str(spy[day]['close'])),'SPY_CLOSE_PREIMAGE')
        if 'spy_open_adjusted' in row:
            need(Q(str(row['spy_open_adjusted']))==Q(str(spy[day]['open'])),'SPY_OPEN_PREIMAGE')
        for sid,quote in row['prices'].items():
            actual=raw_prices[(sid,day)]
            need(Q(quote['raw_open'])==Q(str(actual['open'])) and Q(quote['raw_close'])==Q(str(actual['close'])),'RAW_PRICE_PREIMAGE')
            checked_prices+=1
        for event in row['ledger_today']:
            kind=event['event_type'];sid=event['security_id'];detail=event['detail']
            need(event['session']==day and close(event['cash_before'],cash)
                 and close(event['cash_before']+event['cash_delta'],event['cash_after']),'LEDGER_CASH_CONTINUITY')
            cash=event['cash_after'];need(cash>=-1e-8,'NEGATIVE_CORE_CASH')
            if kind in ('BUY','SELL'):
                need((event['shares_delta']>0)==(kind=='BUY'),'LEDGER_TRADE_SIDE')
                expected=-event['shares_delta']*event['price']-event['fees']
                need(close(event['cash_delta'],expected) and close(event['fees'],abs(event['shares_delta']*event['price'])*.001),'LEDGER_TRADE_CASH_AND_FEE')
                need(Q(str(event['price']))==Q(str(raw_prices[(sid,day)]['open'])),'LEDGER_OPEN_PRICE')
                shares[sid]+=event['shares_delta']
            elif kind=='SPLIT':shares[sid]+=event['shares_delta']
            elif kind=='DIVIDEND_ACCRUED':
                key=(sid,day);need(key not in claims and close(event['cash_delta'],0),'DUPLICATE_DIVIDEND')
                amount=shares[sid]*event['price'];claims[key]=amount
                need(close(detail['amount'],amount),'DIVIDEND_ENTITLEMENT')
            elif kind=='DIVIDEND_PAID':
                key=(sid,detail['accrued_session']);need(key in claims and day==calendar.next_session(key[1]),'DIVIDEND_SETTLEMENT_DATE')
                need(close(claims.pop(key),event['cash_delta']),'DIVIDEND_PAYMENT')
            else:raise ValueError('REFUSED_ALPACA_FIT_UNSUPPORTED_REVIEW_EVENT:'+kind)
            events.append(event)
        actual_shares=defaultdict(float)
        for episode in row['wealth_core']['episodes'].values():actual_shares[episode['security_id']]+=episode['current_shares']
        for sid in set(shares)|set(actual_shares):need(close(shares[sid],actual_shares[sid]),'CORE_SHARES')
        need(close(cash,row['wealth_core']['cash']),'CORE_CASH')
        actual_claims={(r['security_id'],r['accrued_session']):r['amount'] for r in row['core_receivables']}
        need(set(actual_claims)==set(claims) and all(close(claims[k],v) for k,v in actual_claims.items()),'CORE_CLAIMS')
        # A receivable is an economic asset, while spendable cash remains
        # separate. Verify the actual current adapter, not stale ledger prose.
        nav=raw_nav(cash,actual_shares,{sid:raw_prices[(sid,day)]['close'] for sid in actual_shares},claims)
        need(close(nav,row['shadow_nav']),'CORE_RAW_CLOSE_NAV')
        obs=SimpleNamespace(**row['evidence']['observation']);parent=row['decision']['champion_target_core_exposure']
        for key,module in leaves.items():
            leaf_states[key],e=module.step(observation=obs,base_target=parent,state=leaf_states[key])
            need(row['owned55_profiles'][key]=={'state':leaf_states[key],'evidence':e},'REGISTERED_CONTROLLER_PATH')
        need(row['decision']['owned_impairment']==row['owned55_profiles'][baseline.id]['evidence'],'BASELINE_CONTROLLER_PATH')
        if row['phase']=='FORMATION':formation_count+=1;need(day==plan.axis[298+formation_count],'FORMATION_AXIS')
        else:
            need(formation_count==126 and row['phase']=='MEASURED','MEASURED_BEFORE_FORMATION')
            need(day==plan_record['measured_axis'][measured_count],'MEASURED_AXIS');measured_count+=1
        prior=row['state_sha256'];last=day;by_session[day]=row
    reviewed=[]
    for receipt in retained:
        path=root/receipt['file'];need(path.stat().st_size==receipt['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==receipt['sha256'],'RETAINED_CP_FILE')
        value=json.loads(gzip.decompress(path.read_bytes()));cp=value['canonical']
        restored=Formation.resume(cp,plan=plan).state if value['formation'] else SessionState.from_dict(cp)
        need(restored.state_hash==receipt['state_sha256'] and restored.last_processed_session==receipt['session'],'CP_CANONICAL_RESTORE')
        if receipt['file'] in inherited:
            need(receipt==inherited[receipt['file']],'OLD_CHECKPOINT_RECEIPT_UNCHANGED')
        else:
            need(value['source_sha256']==binding and value.get('origin_source_sha256',origin_binding)==origin_binding,'CP_EXECUTION_SOURCE')
            need(value['input_interpretation_sha256']==interpretation,'CP_INPUT_INTERPRETATION')
        need(value['protocol_sha256']==request['protocol_sha256']
             and value['dataset_sha256']==request['dataset_sha256'],'CP_LINEAGE')
        commit=value['journal'];need(prefixes[commit['bytes']]==(commit['sha256'],commit['records'],commit['chain_sha256']),'HISTORICAL_PREFIX')
        row=by_session[value['session']];need(row['state_sha256']==restored.state_hash,'CP_JOURNAL_STATE')
        if value['session'] is not None:
            need(restored.wealth_core==row['wealth_core'] and restored.pending==row['pending']
                 and restored.last_decision==row['decision'] and restored.last_evidence==row['evidence'],'CP_FINANCIAL_CONTROLLER_FIELDS')
            expected_events=[e for r in frames[1:commit['records']] for e in r['ledger_today']]
            need(restored.ledger['events']==expected_events and restored.ledger['receivables']==row['core_receivables'],'CP_FULL_LEDGER')
        for key,module in leaves.items():
            module.validate({'strategy':module.STRATEGY_ID},value['controller_states'][key],expected_session=value['session'])
            if value['session'] is not None:need(value['controller_states'][key]==row['owned55_profiles'][key]['state'],'CP_CONTROLLER_STATES')
        reviewed.append({'file':receipt['file'],'canonical_restore':True,'historical_prefix':True})
    complete=formation_count==126 and measured_count==len(plan_record['measured_axis'])
    if role:need(set(role_records)==set(role_events) and all(v==1 for v in role_records.values()),'REVIEW_ALL_RECIPIENT_PREIMAGES')
    if repair:
        basis=repair['predecessor'];anchor=by_session[basis['checkpoint']['session']]
        need(set(repair_records)==set(repair_events) and all(v==1 for v in repair_records.values())
             and anchor['input_sha256']==basis['input_sha256']
             and anchor['state_sha256']==basis['state_sha256'],'REVIEW_FACTUAL_SOURCE_AND_INPUT_ANCHOR')
    need(formation_count==status['formation_count'] and measured_count==status['measured_records'],'REVIEW_PROGRESS_COUNTS')
    if request.get('continuation'):
        spec=request['continuation'];old_commit=spec['checkpoint']['journal']
        need(prefixes[old_commit['bytes']]==(old_commit['sha256'],old_commit['records'],old_commit['chain_sha256']),
             'UNCHANGED_OWN_COMMITTED_PREFIX')
        new_rows=frames[old_commit['records']:]
        need(not new_rows or new_rows[0]['session']==calendar.next_session(spec['checkpoint']['session']),
             'EXACT_ADJACENT_SUFFIX_START')
        need(set(inherited).issubset(r['file'] for r in retained),'ALL_OLD_CHECKPOINTS_RETAINED')
    need(not complete or status['status']=='CANONICAL_BASELINE_TRACE_COMPLETE','COMPLETE_STATUS')
    result={'schema':'research.alpaca-fit-baseline-independent-review/1','status':'COMPLETE_TRACE_REVIEWED' if complete else 'PARTIAL_PREFIX_REVIEWED',
        'formation_closes':formation_count,'measured_closes':measured_count,'last_committed_session':last,
        'raw_price_preimages':checked_prices,'registered_controller_paths':108,'retained_checkpoints':reviewed,
        'all_journal_bytes_committed':True,'uncommitted_tail_bytes':0,'source_sha256':binding,'origin_source_sha256':origin_binding,
        'old_prefix_and_origin_preserved':bool(request.get('continuation')),
        'input_interpretation_sha256':interpretation,'sparse_factual_amendment':bool(request.get('sparse_input_repair')),
        'funded_account_performance_admitted':False,'production_contacted':False}
    save(out/'independent-review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('evidence','inputs','prefix-inputs','request','output'):p.add_argument('--'+n,required=True)
    a=p.parse_args();review(a.evidence,a.inputs,a.prefix_inputs,json.loads(Path(a.request).read_bytes()),a.output)
