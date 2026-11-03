"""Narrow indexed-prefix/claim/lineage stubs; no canonical execution."""
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
from system_campaign_discovery_suffix_probe import Fence
import system_campaign_discovery_indexed_spinoff_parent as parent
import system_campaign_discovery_indexed_spinoff_replay as replay
import system_campaign_discovery_indexed_spinoff_job as job
import system_campaign_discovery_indexed_spinoff_run as run
from system_campaign_discovery_context import TAINT,digest,encoded
from system_campaign_anchor_proofs import VersionedAnchorProofWriter,PROOF_STATUS,proof_prefix_evidence

def commitment(raw):return dict(bytes=len(raw),prefix_sha256=hashlib.sha256(raw).hexdigest(),last_record_sha256=hashlib.sha256(raw.splitlines(keepends=True)[-1]).hexdigest() if raw else None)

def anchor_stream(records):
 chain=digest(dict(authority=TAINT,stream='retained-anchor-events.jsonl'));raw=b''
 for sequence,record in enumerate(records):
  record=dict(record,sequence=sequence,authority=TAINT);chain=digest(dict(previous=chain,record=record))
  raw+=encoded(dict(record=record,chain_sha256=chain))+b'\n'
 return raw,dict(bytes=len(raw),prefix_sha256=hashlib.sha256(raw).hexdigest(),rows=len(records),chain_sha256=chain)

def index_fixture(tmp_path,monkeypatch,*,body_input='3'*64):
 source='1'*64;input_sha='3'*64;prior='4'*64;after='5'*64
 old=tmp_path/'lineage/diagnostic-predecessor/diagnostic-book';old.mkdir(parents=True)
 oldraw=gzip.compress(b'{"synthetic_flat":true}');(old/'discovery-checkpoint.json.gz').write_bytes(oldraw)
 oldsha=hashlib.sha256(oldraw).hexdigest();predecessor=dict(checkpoint_sha256=oldsha)
 record=dict(security_id='S',session='2018-01-02',raw_close=10.0,signal_close=20.0)
 anchors=SimpleNamespace(source_sha256=source,input_sha256=body_input,records={'S':SimpleNamespace(model_dump=lambda:deepcopy(record))})
 writer=VersionedAnchorProofWriter(tmp_path,anchors,predecessor=predecessor)
 proof=dict(status=PROOF_STATUS,financial_authority=False,historical_auxiliary_only=True,current_bars_unchanged=True,
  window_dates=300,security_ids=['S'],prior_state_sha256=prior,next_state_sha256=after,session='2021-01-04')
 writer.write(proof);selected=writer.commitment()
 writer.write(dict(proof,session='2021-01-05',prior_state_sha256=after,next_state_sha256='6'*64))
 (tmp_path/'anchor-qualifications/orphan.json').write_bytes(b'{"synthetic_uncommitted":true}\n')
 rows=[dict(session='2021-01-01',state_sha256=prior),dict(session='2021-01-04',state_sha256=after)]
 daily=b''.join(encoded(r)+b'\n' for r in rows);book=tmp_path/'diagnostic-book';book.mkdir();(book/'daily.jsonl').write_bytes(daily+b'UNSENT_DAILY')
 (book/'retained-checkpoints').mkdir()
 raw,anchor_commit=anchor_stream([dict(session='2021-01-04',security_id='S',prior_state_sha256=prior,
  source_anchor=record,source_sha256=source,input_sha256=input_sha)])
 (tmp_path/'retained-anchor-events.jsonl').write_bytes(raw+b'UNSENT_ANCHOR')
 saved=dict(diagnostic_predecessor=predecessor,retained_anchor_qualifications=selected,
  retained_source_anchors=anchor_commit,journals={'daily':commitment(daily)})
 evidence=proof_prefix_evidence(tmp_path,selected,predecessor=predecessor)
 body=evidence['committed_proofs'][0]['record'];seed=dict(body['qualification'],source_sha256=body['source_sha256'],
  input_sha256=body['input_sha256'],source_records=body['source_records'],source_records_sha256=body['source_records_sha256'])
 spec=dict(arm='P03',source_sha256=source,input_sha256=input_sha,initial_flat_seed_count=0,combined_committed_seed_count=1,
  combined_committed_seed_sha256=digest([seed]),retained_anchor_qualifications=selected,old_diagnostic_reference=predecessor,
  old_index_evidence={k:v for k,v in evidence.items() if k!='committed_proofs'})
 real=parent.original
 stub=SimpleNamespace(specification=lambda arm:dict(diagnostic_checkpoint='diagnostic-book/discovery-checkpoint.json.gz',diagnostic_checkpoint_sha256=oldsha),
  validate_checkpoint=lambda cp,spec:cp,verify_chain=real.verify_chain,verify_prefix=real.verify_prefix)
 monkeypatch.setattr(parent,'original',stub);monkeypatch.setattr(parent,'qualified_anchor_seeds',lambda *a:[])
 return saved,spec

def test_indexed_seed_adopts_only_committed_use_and_preserves_full_index_orphan_tails(tmp_path,monkeypatch):
 saved,spec=index_fixture(tmp_path,monkeypatch)
 seeds,evidence=parent.indexed_seeds(tmp_path,saved,spec)
 assert len(seeds)==1 and seeds[0]['session']=='2021-01-04'
 assert evidence['uncommitted_index']['bytes']>0 and len(evidence['uncommitted_proof_files'])==2
 assert (tmp_path/'anchor-qualifications/orphan.json').read_bytes()==b'{"synthetic_uncommitted":true}\n'

def test_actual_source_input_guard_removal_falsifier(tmp_path,monkeypatch):
 saved,spec=index_fixture(tmp_path,monkeypatch,body_input='9'*64)
 with pytest.raises(ValueError,match='ONLY_ACTUAL_COMMITTED_SOURCE_INPUT'):parent.indexed_seeds(tmp_path,saved,spec)
 fn=next(n for n in ast.parse(Path(parent.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='indexed_seeds')
 removed=[]
 for loop in ast.walk(fn):
  if isinstance(loop,ast.For):
   for node in list(loop.body):
    if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant)
     and v.value=='INDEXED_SPIN_ONLY_ACTUAL_COMMITTED_SOURCE_INPUT_PRIOR_AND_NEXT_STATE_QUALIFIED_SEED' for v in node.value.args):
     loop.body.remove(node);removed.append(node)
 assert len(removed)==1;scope=dict(vars(parent))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-indexed-input-guard-removed>','exec'),scope)
 seeds,_=scope['indexed_seeds'](tmp_path,saved,spec);assert seeds[0]['input_sha256']=='9'*64

def claim_event():
 claim=dict(schema_id='research.diagnostic-unvalued-spinoff-claim/1',authority=TAINT,session='2021-11-08',parent_ticker='BFH',
  parent_security_id='S',child_ticker=None,child_security_id=None,source_row_id='a'*64,entitlement_status='UNRESOLVED_UNVALUED_NOT_SETTLED',
  parent_episode_facts=[dict(slot_id=0,current_shares=7)],roles=['HELD'],financial_authority=False)
 term={k:claim[k] for k in ('session','parent_ticker','parent_security_id','child_ticker','child_security_id','source_row_id')}
 proof=dict(authority=TAINT,session=claim['session'],input_sha256='2'*64,prior_state_sha256='3'*64,financial_authority=False,
  all_supplied_held_legs_deferred=True,partial_application=False,affected_held_legs=[dict(source_term=term,unresolved_claim=claim,
  parent_episode_facts=deepcopy(claim['parent_episode_facts']),roles=['HELD'],disposition='UNRESOLVED_UNVALUED_NOT_SETTLED')],
  native_source_legs=[dict(source_row_id='a'*64)])
 return dict(kind='SPINOFF_UNRESOLVED_ENTITLEMENT_DEFERRED',authority=TAINT,sequence=0,session=claim['session'],
  prior_state_sha256='3'*64,source_sha256='1'*64,input_sha256='2'*64,context=dict(bypass=True,entitlement_proof=proof))

def test_claims_survive_parent_absence_and_restart_from_committed_prefix_only(tmp_path):
 event=claim_event();events=[event,dict(kind='CORE_TRANSITION_COMMITTED',session='2021-11-09')]
 claims=replay.reconstruct_claims(events,source_sha256='1'*64,input_sha256='2'*64);assert len(claims)==1
 chain=digest(dict(previous=digest(dict(authority=TAINT)),event=event));raw=encoded(dict(event=event,chain_sha256=chain))+b'\n'
 previous=tmp_path/'previous';previous.mkdir();(previous/'discovery-events.jsonl').write_bytes(raw+b'UNSENT_MALFORMED_CLAIM_TAIL')
 commit=dict(bytes=len(raw),prefix_sha256=hashlib.sha256(raw).hexdigest(),rows=1,chain_sha256=chain)
 saved=dict(events=commit,discovery_transitions=883,runtime_checkpoint={'input_sha256':'2'*64},
  unvalued_spinoff_claims=replay.claim_commitment(claims,commit))
 out=tmp_path/'out';out.mkdir();context=replay.ContinuedContext(out,source_sha256='1'*64,previous=previous,saved=saved)
 assert context.unvalued_claims==claims and (out/'discovery-events.jsonl').read_bytes()==raw
 assert b'UNSENT' in (previous/'discovery-events.jsonl').read_bytes()
 out2=tmp_path/'bad';out2.mkdir();bad=deepcopy(saved);bad.pop('unvalued_spinoff_claims')
 with pytest.raises(ValueError,match='NEVER_RESTARTED'):replay.ContinuedContext(out2,source_sha256='1'*64,previous=previous,saved=bad)

@pytest.mark.parametrize('change',['input','native-leg','invented-quantity','default-fields'])
def test_claim_registry_refuses_scope_or_omission_or_invented_terms(change):
 event=claim_event();claim=event['context']['entitlement_proof']['affected_held_legs'][0]['unresolved_claim']
 if change=='input':event['input_sha256']='9'*64
 if change=='native-leg':event['context']['entitlement_proof']['native_source_legs']=[]
 if change=='invented-quantity':claim['child_shares']=7
 if change=='default-fields':claim.pop('financial_authority')
 with pytest.raises(ValueError):replay.reconstruct_claims([event],source_sha256='1'*64,input_sha256='2'*64)

def test_actual_claim_wire_completeness_guard_removal_falsifier():
 event=claim_event();event['context']['entitlement_proof']['affected_held_legs'][0]['unresolved_claim'].pop('financial_authority')
 with pytest.raises(ValueError,match='EXPLICIT_FULL_UNVALUED_CLAIM'):replay.add_claims({},event,source_sha256='1'*64,input_sha256='2'*64)
 fn=next(n for n in ast.parse(Path(replay.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='add_claims')
 removed=[]
 for loop in ast.walk(fn):
  if isinstance(loop,ast.For):
   for node in list(loop.body):
    if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant)
     and v.value=='INDEXED_SPIN_EXPLICIT_FULL_UNVALUED_CLAIM_NO_DEFAULTS_OR_QUANTITY_INVENTION' for v in node.value.args):
     loop.body.remove(node);removed.append(node)
 assert len(removed)==1;scope=dict(vars(replay))
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-claim-wire-guard-removed>','exec'),scope)
 claims={};scope['add_claims'](claims,event,source_sha256='1'*64,input_sha256='2'*64);assert len(claims)==1

def test_flat_lineage_retains_current_full_streams_and_all_earlier_epochs_once(tmp_path):
 previous=tmp_path/'previous';previous.mkdir();old=b'{}\n';full=old+b'UNSENT\n'
 values={'diagnostic-book/discovery-checkpoint.json.gz':b'CURRENT_CP','discovery-events.jsonl':b'FULL_EVENTS_WITH_TAIL',
  'retained-anchor-events.jsonl':b'FULL_ANCHORS_WITH_TAIL','anchor-qualifications/index.jsonl':b'COMPLETE_INDEX_AND_TAIL',
  'anchor-qualifications/orphan.json':b'ORPHAN_PROOF','lineage/diagnostic-predecessor/old-cp.json.gz':b'OLD_CP',
  'lineage/diagnostic-predecessor/actual-anchor-qualification.json':b'FLAT_OLD_PROOF'}
 for name in ('daily','formation','monthly','watch'):values['diagnostic-book/'+name+'.jsonl']=full
 inventory={}
 for name,raw in values.items():
  path=previous/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
  inventory[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
 epoch={n[len('lineage/diagnostic-predecessor/'):]:e for n,e in inventory.items() if n.startswith('lineage/')};epochsha=digest(epoch)
 spec=dict(full_inventory=inventory,diagnostic_checkpoint_sha256='0'*64,
  retained_lineage_epochs=[dict(source_prefix='lineage/diagnostic-predecessor/',epoch_sha256=epochsha,inventory=epoch)])
 saved=dict(journals={n:commitment(old) for n in ('daily','formation','monthly','watch')})
 out=tmp_path/'out';out.mkdir();replay.seed_book(out/'diagnostic-book',previous,saved,spec)
 assert (out/'diagnostic-book/daily.jsonl').read_bytes()==full
 assert (out/'lineage/diagnostic-predecessor/anchor-qualifications/index.jsonl').read_bytes()==b'COMPLETE_INDEX_AND_TAIL'
 assert (out/'lineage/diagnostic-predecessor/anchor-qualifications/orphan.json').read_bytes()==b'ORPHAN_PROOF'
 assert (out/'lineage/epochs'/epochsha/'old-cp.json.gz').read_bytes()==b'OLD_CP'
 assert not (out/'lineage/diagnostic-predecessor/lineage').exists()
 assert all((previous/n).read_bytes()==v for n,v in values.items())

def test_exact431_inheritance_and_own_indexed_parent_scopes():
 value=job.expected_request();assert len(value['sources'])==439 and value['arms']==['P03','P05']
 assert value['seed_counts']==dict(P03=2,P05=3) and value['indexed_anchor_proof_successor']
 assert not value['financial_state_adopted'] and not value['canonical_financial_source_changed'] and not value['new_origin']
 assert value['source_bound_spinoff_deferral_selected'] and value['no_spinoff_receipt_liquidation_cash_or_receivable']
 for arm,count in [('P03',883),('P05',1175)]:assert parent.specification(arm)['transitions']==count

def test_actual_namespace_ast_keeps_canonical_runtime_recovery_crypto_and_first_use_guards():
 tree=run.main_tree();text=ast.unparse(tree)
 assert "args.arm in ('P03', 'P05')" in text and 'runtime.restore' in text and 'runtime.checkpoint(run)' in text
 tree=replay.suffix_tree(replay.original.proven.exact_raw(replay.original.original));text=ast.unparse(tree)
 assert 'runtime.advance(run, published)' in text and 'recovered_stream(book, saved)' in text
 assert 'first.prepare(buffer, run)' in text and 'first.after(run, next_run)' in text
 assert 'unvalued_spinoff_claims=context.claim_commitment()' in text
 assert 'retained_anchor_qualifications=anchor_gate.commitment()' in text
 compile(tree,'<indexed-suffix-static-only>','exec')
 text=ast.unparse(parent.admission_tree())
 assert text.index('authenticate(z, asset, key)')<text.index('tarfile.open(')<text.index('validate_contents(')
 assert "'phase.json'" in text and "'export-qualification.json'" in text
 fn=job.method('main',dict(specification=parent.specification,admit_diagnostic=parent.admit,expected_request=job.expected_request,
  worker_command=job.worker_command,inspect=job.inspect,SELECTED_ARMS=parent.ARMS))
 for name in ('qualify_export','finish_export','phase','stopped_run'):assert fn.__globals__[name] is getattr(job.original,name)

def test_worker_command_capacity_order_and_outer_budgets(monkeypatch,tmp_path):
 monkeypatch.setattr(job.original.os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(job.original.os,'getgid',lambda:1001,raising=False)
 for arm in parent.ARMS:
  cmd=job.worker_command('capital-system-diagnostic-indexed-spin-'+arm.lower()+'-worker-123-1',arm,
   tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old',tmp_path/'previous')
  assert cmd[cmd.index('-B'):]==job.entrypoint(arm) and cmd.count('--mount')==6
  assert cmd[cmd.index('--memory')+1]==cmd[cmd.index('--memory-swap')+1]=='8g'
  assert cmd[cmd.index('--cpus')+1]=='2' and cmd[cmd.index('--network')+1]=='none'
 with pytest.raises(ValueError):job.entrypoint('P06')
 raw=(HERE.parents[1]/'.github/workflows/capital-system-discovery-indexed-spinoff.yml').read_text()
 assert raw.index('/ephemeral_runner_capacity.py')<raw.index('/stage.py')<raw.index('/system_campaign_discovery_indexed_spinoff_job.py')
 assert 'timeout-minutes: 360' in raw and 'timeout-minutes: 335' in raw and 'timeout-minutes: 5' in raw and 'timeout-minutes: 8' in raw
 assert 'workflow_dispatch' not in raw and 'fail-fast: false' in raw and 'retention-days: 7' in raw

@pytest.mark.parametrize('change',[None,'old-entrypoint','wrong-arm','writable-previous','network','credential'])
def test_actual_new_namespace_inspection_keeps_all_fences(monkeypatch,change):
 monkeypatch.setattr(job.original.os,'getuid',lambda:1001,raising=False);monkeypatch.setattr(job.original.os,'getgid',lambda:1001,raising=False)
 name='capital-system-diagnostic-indexed-spin-p03-worker-123-1'
 value=dict(Name='/'+name,Image=job.original.inspector_source.EXECUTION_IMAGE,Id='a'*64,
  HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,PidsLimit=64,
   ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
  Config=dict(Cmd=job.entrypoint('P03'),WorkingDir='/variant',User='1001:1001',
   Labels={'research.study':'full-system-search-20261029','research.role':'worker'},Env=[]),
  Mounts=[dict(Type='bind',Destination=n,RW=n=='/out') for n in ('/variant','/frozen','/driver','/out','/old','/previous')])
 if change=='old-entrypoint':value['Config']['Cmd'][2]='/driver/system_campaign_discovery_suffix_run.py'
 if change=='wrong-arm':value['Config']['Cmd']=job.entrypoint('P05')
 if change=='writable-previous':value['Mounts'][-1]['RW']=True
 if change=='network':value['HostConfig']['NetworkMode']='bridge'
 if change=='credential':value['Config']['Env']=['GH_TOKEN=private']
 monkeypatch.setattr(job.original.inspector_source.subprocess,'run',lambda *a,**kw:SimpleNamespace(stdout=json.dumps([value]).encode()))
 if change:
  with pytest.raises(ValueError):job.inspect(name,'a'*64)
 else:assert job.inspect(name,'a'*64)==value

@pytest.mark.parametrize('arm',parent.ARMS)
def test_actual_arm_marker_roundtrip_for_changed_request_before_parent_or_worker(tmp_path,monkeypatch,arm):
 monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
 request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='2'*64,synthetic_transport_test=True)))
 proof=job.original.qualify_export(tmp_path/('marker-'+arm),request,arm)
 assert proof['status']=='PARALLEL_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
 assert proof['arm']==arm and proof['request_sha256']==hashlib.sha256(request.read_bytes()).hexdigest()
 assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']
