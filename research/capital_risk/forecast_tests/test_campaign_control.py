"""Campaign DATA classification and source-readiness guards; no financial engine."""
import ast,gzip,json,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
import system_campaign_control as p

def stop(code=0,oom=False):return dict(stopped=True,exit_code=code,oom_killed=oom)

def test_actual_admitted_dates_and_counts_are_primary_reporting():
 rows=p.accepted_status();assert len(rows)==12 and sum(r['complete'] for r in rows)==7
 assert sum(r['completed'] for r in rows)==20395
 assert next(r for r in rows if r['arm']=='P06')['through']=='2023-08-31'

@pytest.mark.parametrize('role',['preflight','worker','reviewer'])
def test_noncanonical_stopped_failure_receipts_classified_by_primary_stage(role):
 value=dict(EXPLICIT_NONCANONICAL_RECEIPT_DTO=True,status='FINANCIAL_REVIEW_REFUSED_PRESERVED',preflight=stop(),worker=stop(),reviewer=stop())
 value[role]=stop(1)
 if role=='worker':value['reviewer']=stop(1)
 assert p.classify_receipt(value)['stage']=='FAILED_'+role.upper()
 assert p.classify_receipt(value)['retry_authorized'] is False

def test_reviewed_partial_is_useful_but_does_not_grant_admission_or_retry():
 value=dict(EXPLICIT_NONCANONICAL_RECEIPT_DTO=True,status='PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT',preflight=stop(),worker=stop(1),reviewer=stop())
 assert p.classify_receipt(value)==dict(stage='REVIEWED_PARTIAL_PENDING_INDEPENDENT_ADMISSION',admission_required=True,retry_authorized=False)
 value['worker']=stop(137,True);assert p.classify_receipt(value)['stage']=='FAILED_WORKER'

def test_source_capture_success_is_never_a_financial_admission():
 value=dict(EXPLICIT_NONCANONICAL_RECEIPT_DTO=True,status='SOURCE_BATCH_CAPTURED',worker=stop(),financial_authority=False)
 assert p.classify_receipt(value)==dict(stage='SOURCE_DATA_PENDING_INDEPENDENT_QUALIFICATION',admission_required=False,source_qualification_required=True,retry_authorized=False)
 value['worker']['stopped']=False;assert p.classify_receipt(value)['stage']=='UNKNOWN'

@pytest.mark.parametrize('change',['status','stop','exit_type','oom_type'])
def test_unknown_outcomes_never_promoted(change):
 value=dict(EXPLICIT_NONCANONICAL_RECEIPT_DTO=True,status='PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT',preflight=stop(),worker=stop(),reviewer=stop())
 if change=='status':value['status']='WRITER_UNKNOWN_NO_MUTABLE_EXPORT'
 elif change=='stop':value['worker']['stopped']=False
 elif change=='exit_type':value['worker']['exit_code']=False
 else:value['worker']['oom_killed']=None
 assert p.classify_receipt(value)['stage']=='UNKNOWN'

def profile_DTO(tmp_path):
 source=tmp_path/'EXPLICIT_NONCANONICAL_SOURCE.py';source.write_text('EXPLICIT_NONCANONICAL_SOURCE=True\n')
 accepted=next(r for r in p.accepted_status() if r['arm']=='P06')
 q=dict(EXPLICIT_NONCANONICAL_PROFILE_DTO=True,passed=True,financial_profile_ready=True,financial_authority=False,
  root_admission_sha256=accepted['root'],files={source.name:dict(bytes=source.stat().st_size,sha256=p.sha(source.read_bytes()))})
 name='EXPLICIT_NONCANONICAL_QUALIFICATION.json';(tmp_path/name).write_bytes(p.encoded(q))
 return dict(arm='P06',event='EXPLICIT_NONCANONICAL_EVENT',profile_qualification=name),accepted,q

def test_ready_profile_requires_matching_root_and_every_actual_source_pin(tmp_path):
 record,accepted,q=profile_DTO(tmp_path)
 assert p.qualified_profile(tmp_path,record,accepted)[0] is True
 (tmp_path/'EXPLICIT_NONCANONICAL_SOURCE.py').write_text('CHANGED=True\n')
 assert p.qualified_profile(tmp_path,record,accepted)==(False,'PROFILE_SOURCE_CHANGED')

def test_owner_choice_guard_and_meaningful_removal(tmp_path):
 record,accepted,q=profile_DTO(tmp_path);record['requires_owner_choice']=True
 assert p.qualified_profile(tmp_path,record,accepted)==(False,'OWNER_CHOICE_REQUIRED')
 fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='qualified_profile')
 first=fn.body.pop(0);assert ast.unparse(first.test)=="record.get('requires_owner_choice')"
 scope=dict(vars(p));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-owner-choice-guard-DATA-test>','exec'),scope)
 assert scope['qualified_profile'](tmp_path,record,accepted)[0] is True

def test_active_arm_cannot_be_selected_twice(tmp_path,monkeypatch):
 record,_,_=profile_DTO(tmp_path)
 rows=p.accepted_status();monkeypatch.setattr(p,'accepted_status',lambda driver:rows)
 actions=p.next_actions(tmp_path,dict(next_events=[record]),active_arms=('P06',))
 assert actions['ready']==[] and actions['blocked'][0]['reason']=='ACTIVE_JOB_NO_DUPLICATE'
 assert actions['automatic_launch_authority'] is False

def test_inventory_covers_entire_remaining_provider_interval_and_keeps_unknowns():
 value=json.loads((C/'system-campaign-event-inventory.json').read_bytes())
 raw=(C/value['events_file']).read_bytes();assert p.sha(raw)==value['events_file_sha256']
 events=json.loads(gzip.decompress(raw))['events']
 assert value['groups']==6922 and value['raw_rows']==9922 and value['provider_sha256']==p.PROVIDER_SHA
 assert value['financial_authority'] is value['full_frozen_native_event_coverage_verified'] is False
 assert len(events)==value['groups']
 assert all(e['runtime_qualification']==e['event_date_ownership']=='UNKNOWN' for e in events)
 assert any(e['ticker']=='STML' for e in events) and any(e['ticker']=='BWA' for e in events)
 assert any(e['ticker']=='WWE' for e in events) and any(e['ticker']=='BRG' for e in events)

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_no_financial_import(name):assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
