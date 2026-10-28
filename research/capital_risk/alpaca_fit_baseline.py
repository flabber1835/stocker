"""Hosted canonical baseline and retained-prefix timing gate. Never a GO book."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

from alpaca_fit_inputs import Inputs,hosted,need


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'


def save(path,value):
    need(not path.exists(),'OUTPUT_COLLISION')
    with path.open('xb') as f:f.write(encoded(value));f.flush();os.fsync(f.fileno())


class Journal:
    def __init__(self,path):self.path=path;self.hash=hashlib.sha256();self.count=0;self.length=0;self.chain='0'*64
    def append(self,value):
        value={'previous_chain_sha256':self.chain,**value};raw=encoded(value)
        self.chain=hashlib.sha256(raw).hexdigest();self.hash.update(raw);self.count+=1;self.length+=len(raw)
        with self.path.open('ab') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    def commitment(self):return {'file':self.path.name,'bytes':self.length,'sha256':self.hash.hexdigest(),'records':self.count,'chain_sha256':self.chain}


def source_check(root,expected):
    for name,spec in expected.items():
        path=(root/name).resolve();need(root.resolve() in path.parents and path.is_file(),'SOURCE_PATH')
        need(path.stat().st_size==spec['bytes'] and hashlib.sha256(path.read_bytes()).hexdigest()==spec['sha256'],'SOURCE_BINDING:'+name)
    return hashlib.sha256(encoded(expected)).hexdigest()


def run(args):
    hosted();started=time.monotonic();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    request=json.loads(Path(args.request).read_bytes());protocol=json.loads(Path(args.protocol).read_bytes())
    need(hashlib.sha256(Path(args.protocol).read_bytes()).hexdigest()==request['protocol_sha256'],'WORKER_PROTOCOL')
    need(request['stage']=='INPUT_AND_CANONICAL_BASELINE','WORKER_SCOPE')
    binding=source_check(Path('/src'),request['source_files']);save(out/'source-bindings.json',request['source_files'])
    from sentinel.strategy import production_strategy
    from sentinel.core.formation import Formation,FormationPlan
    from sentinel.core.session import SessionState
    from sentinel.core.kernel import advance_session
    from sentinel.controller.machine import Observation
    from sentinel.controller import owned_impairment
    from sentinel.feed import calendar
    from sentinel.feed.rolling_contract import digest
    import sentinel.core.kernel as kernel
    need(Path(kernel.__file__).resolve()==Path('/src/sentinel/core/kernel.py'),'EMBEDDED_OR_FOREIGN_KERNEL')
    controller,identity=production_strategy()
    from alpaca_fit_policy import profiles,leaf
    registered,baseline_profile=profiles(protocol)
    leaf_source=Path('/src/sentinel/controller/owned_impairment.py')
    leaf_sha=hashlib.sha256(leaf_source.read_bytes()).hexdigest()
    leaves={profile.id:leaf(leaf_source,profile,leaf_sha) for profile in registered}
    leaf_states={key:module.fresh() for key,module in leaves.items()}
    save(out/'controller-profiles.json',{key:module.research_identity for key,module in leaves.items()})
    save(out/'controller-component-qualification-reference.json',request['reused_component_qualification'])
    journal=Journal(out/'canonical.jsonl');qualifications=[];retained=[];book=None;state=None;times=[]
    status='BASELINE_INCOMPLETE';failure=None;current_phase='INPUT_AUTHENTICATION';last=None
    def checkpoint(tag,formation):
        value={'schema':'research.alpaca-fit-baseline-checkpoint/1','source_sha256':binding,
            'protocol_sha256':request['protocol_sha256'],'dataset_sha256':request['dataset_sha256'],
            'formation':formation,'canonical':book.checkpoint() if formation else state.to_dict(),
            'journal':journal.commitment(),'session':state.last_processed_session,'controller_states':leaf_states}
        raw=encoded(value);path=out/(tag+'.json.gz')
        with path.open('xb') as f:f.write(gzip.compress(raw,compresslevel=1,mtime=0));f.flush();os.fsync(f.fileno())
        restored=json.loads(gzip.decompress(path.read_bytes()))
        canonical=Formation.resume(restored['canonical'],plan=plan).state if formation else SessionState.from_dict(restored['canonical'])
        need(canonical.state_hash==state.state_hash and canonical.to_dict()==state.to_dict(),'CHECKPOINT_CANONICAL_ROUNDTRIP')
        need(set(restored['controller_states'])==set(leaves),'CONTROLLER_CHECKPOINT_COVERAGE')
        for key,module in leaves.items():
            module.validate({'strategy':module.STRATEGY_ID},restored['controller_states'][key],expected_session=state.last_processed_session)
            need(restored['controller_states'][key]==leaf_states[key],'CONTROLLER_CHECKPOINT_ROUNDTRIP')
        with journal.path.open('rb') as f:prefix=f.read(value['journal']['bytes'])
        need(len(prefix)==value['journal']['bytes'] and hashlib.sha256(prefix).hexdigest()==value['journal']['sha256'],'JOURNAL_PREFIX')
        retained.append({'file':path.name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'state_sha256':state.state_hash,'session':state.last_processed_session,'canonical_roundtrip':True,'journal':value['journal']})
        save(out/(tag+'-receipt.json'),retained[-1])
    try:
        data=Inputs(Path(args.inputs),Path(args.bil_inputs),protocol,request['dataset_sha256'],Path(args.prefix_inputs))
        save(out/'normalization.json',data.summary)
        save(out/'action-input-issues.json',data.action_issues)
        measured=calendar.sessions_in_range(protocol['measured_start'],protocol['data_end'])
        end=calendar.previous_sessions(protocol['measured_start'],2)[0]
        plan=FormationPlan(end=end,capital=protocol['capital'],warmup_sessions=299,formation_sessions=126,
            strategy=identity,source_sha256=binding,metadata_policy='CURRENT_INFORMATION_INITIALIZATION_V1')
        need(plan.axis[-1]==end and all(d in data.index for d in plan.axis),'FORMATION_AXIS')
        save(out/'plan.json',{'plan':plan.model_dump(by_alias=True),'measured_axis':measured,'source_sha256':binding})
        current_phase='CANONICAL_FEATURE_WARMUP';warm_start=time.monotonic()
        window,admission=data.warmup(plan.axis[:299]);book=Formation(plan,window,data_version=1);state=book.state
        del window
        journal.append({'phase':'WARMUP_ORIGIN','session':None,'state_sha256':state.state_hash,
            'warmup_identity':book.warmup_identity,'admission':admission,'source_sha256':binding})
        checkpoint('warmup-origin',True);warm_seconds=time.monotonic()-warm_start
        save(out/'warmup-timing.json',{'seconds':warm_seconds,'total_elapsed':time.monotonic()-started,'formation_transitions':0})
        sequence=[(d,'FORMATION') for d in plan.axis[299:]]+[(d,'MEASURED') for d in measured]
        last_month=None
        for number,(day,phase) in enumerate(sequence):
            current_phase=phase;before=state;before_hash=before.state_hash;t0=time.monotonic()
            formation=phase=='FORMATION';version=1 if formation else 2+measured.index(day)
            sample=number in (0,4,125,126) or day[:7]!=last_month
            published,admission,qualification=data.published(before,day,version,formation=formation,qualify=sample)
            if qualification:qualifications.append(qualification)
            input_sha=digest(asdict(published));prior_events=len(before.ledger['events'])
            if formation:book.advance(published);state=book.state
            else:state=advance_session(before,published,controller_config=controller,strategy_identity=identity)
            need(before.state_hash==before_hash,'IMMUTABLE_PREDECESSOR')
            observation=Observation(**state.last_evidence['observation'])
            parent=state.last_decision['champion_target_core_exposure'];leaf_rows={}
            for key,module in leaves.items():
                leaf_states[key],evidence=module.step(observation=observation,base_target=parent,state=leaf_states[key])
                leaf_rows[key]={'state':leaf_states[key],'evidence':evidence}
            need(leaf_states[baseline_profile.id]==state.owned_impairment
                 and leaf_rows[baseline_profile.id]['evidence']==state.last_decision['owned_impairment'],'BASELINE_LEAF_CANONICAL_PARITY')
            events=state.ledger['events'][prior_events:]
            ids={e['security_id'] for s in (before,state) for e in s.wealth_core.get('episodes',{}).values()}
            # Prices are selected by immutable security ID, never display ticker.
            quotes={sid:{'raw_open':str(data.row(sid,day)['open']),'raw_close':str(data.row(sid,day)['close'])}
                for sid in ids if sid in data.assets and data.paired(sid,day)}
            journal.append({'phase':phase,'session':day,'data_version':version,'prior_state_sha256':before_hash,
                'state_sha256':state.state_hash,'input_sha256':input_sha,'snapshot_sha256':published.window_features['snapshot_sha256'],
                'features_sha256':digest(published.window_features),'admission':admission,
                'wealth_core':state.wealth_core,'pending':state.pending,'ledger_today':events,'prices':quotes,
                'core_receivables':state.ledger['receivables'],'shadow_nav':state.last_evidence['observation']['shadow_nav'],
                'decision':state.last_decision,'evidence':state.last_evidence,
                'owned55_profiles':leaf_rows,'baseline_private_leaf_complete_equality':True,
                'defensive_bar':asdict(published.defensive_bar),'defensive_previous_bar':asdict(published.defensive_previous_bar),
                'spy_close_adjusted':published.spy_closeadj[-1]})
            elapsed=time.monotonic()-t0
            comparison=0 if qualification is None else qualification['canonical_comparison_seconds']
            times.append({'total_seconds':elapsed,'comparison_seconds':comparison,'ordinary_seconds':elapsed-comparison});last=day
            if number==4:
                checkpoint('formation-prefix-005',True)
                remaining_samples=len({d[:7] for d,_ in sequence[5:]})+2
                projected=time.monotonic()-started+1.5*(max(t['ordinary_seconds'] for t in times[-3:])*(len(sequence)-5)
                    +max(q['canonical_comparison_seconds'] for q in qualifications)*remaining_samples)+180
                timing={'actual_transitions':5,'transition_seconds':times,'elapsed':time.monotonic()-started,
                    'conservative_projected_total_seconds':projected,'ceiling_seconds':protocol['initial_worker_seconds'],
                    'prefix_retained_no_restart':True,'full_run_admitted':projected<protocol['initial_worker_seconds']}
                save(out/'timing-gate.json',timing)
                if not timing['full_run_admitted']:raise ValueError('REFUSED_ALPACA_FIT_MEASURED_THROUGHPUT_BOUND')
            if number==125 or number==len(sequence)-1 or day[:7]!=last_month:
                checkpoint('checkpoint-'+day,formation)
            last_month=day[:7]
            if time.monotonic()-started>protocol['initial_worker_seconds']-180:
                checkpoint('bounded-stop-'+day,formation);raise ValueError('REFUSED_ALPACA_FIT_PROCESSING_BOUND')
        status='CANONICAL_BASELINE_TRACE_COMPLETE'
    except Exception as exc:
        failure={'type':type(exc).__name__,'message':str(exc),'phase':current_phase,'last_committed_session':last}
        save(out/'failure.json',failure)
        if state is not None and last is not None and not any(r['session']==last for r in retained):checkpoint('refused-prefix-'+last,current_phase=='FORMATION')
    finally:
        save(out/'feature-qualification.json',{'actual_boundary_samples':qualifications,'all_equal':bool(qualifications)})
        save(out/'retained-checkpoints.json',retained)
        save(out/'baseline-status.json',{'schema':'research.alpaca-fit-baseline-status/1','status':status,'failure':failure,
            'last_committed_session':last,'formation_count':None if book is None else book.count,
            'measured_records':max(0,journal.count-1-(0 if book is None else book.count)),
            'journal':journal.commitment(),'elapsed_seconds':time.monotonic()-started,
            'source_sha256':binding,'utc':datetime.now(timezone.utc).isoformat(),'production_contacted':False,
            'optimization_performance_admitted':False})
    return 0 if status=='CANONICAL_BASELINE_TRACE_COMPLETE' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('request','protocol','inputs','prefix-inputs','bil-inputs','output'):p.add_argument('--'+name,required=True)
    raise SystemExit(run(p.parse_args()))
