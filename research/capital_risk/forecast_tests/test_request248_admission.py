"""Read the registered saved result and unchanged parent; no financial replay."""
import ast,json,sys
from pathlib import Path
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('REQUEST248_ADMISSION_METADATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_financial_partial as p
OLD='b134772ff8128b4f97a16dabbc357f07e019351c529c03419cb778726fad5a59'
ROOT='4fd19a57b5a982d1e031a6c7b8916ffdb605dbbb57b39f3f9f5bdf073a63b444'

def test_registered_twenty_day_result_keeps_original_parent_and_stops():
 spec=p.root_spec('P07');a=spec['root_admission'];old=p.root_spec('P07',OLD)
 assert spec['root_admission_sha256']==ROOT and a['parent_root_admission_sha256']==OLD
 assert (a['completed'],a['source_cursor'],a['new_daily_records'],a['independent_accounting_snapshots'])==(1446,'2023-09-29',20,40)
 assert len(a['repairs'])==28 and (old['measured_closes'],len(old['repairs']))==(1426,27)
 assert [a['original_financial_stops'][r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,0]
 assert [old['root_admission']['original_financial_stops'][r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,1]
 assert a['original_financial_receipt_status']=='PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'
 assert 'failed_review_requalification' not in a and 'fresh_readonly_stops' not in a
 assert 'root_request238_requalified_review_parent' not in spec and 'qualified_review_transport_sha256' not in spec
 assert a['full_financial_validation_completed'] is a['performance_scoring_authorized'] is a['local_canonical_runtime_executed'] is False
 assert a['branch_uncertainty_proof']['complete_ABMD_and_KDNY_intervals_preserved'] is True
 assert a['source_input_proof']==a['cash_input_proof']
 assert a['uncommitted_tail_commitments']['daily']['unadmitted_tail']['bytes']==298441
 assert p.reviewed_archive_limit(spec)==1024**3

def test_registered_qualification_has_immutable_guard_and_evidence_commitments():
 q=json.loads((C/'P07-request248-independent-DATA-qualification.json').read_bytes());a=p.root_spec('P07')['root_admission']
 assert p.sha((C/'P07-request248-independent-DATA-qualification.json').read_bytes())==a['independent_validation_sha256']==a['independent_financial_DATA_qualification_sha256']
 fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='reviewed_archive_limit')
 assert p.sha(ast.dump(fn,include_attributes=False).encode())==q['reviewed_archive_limit_AST_sha256']
 assert q['counts']==dict(daily=20,accountings=40,new_monthly_reports=1,independent_decimal_metrics=28,retained_proofs=972,new_proofs=20,full_inputs=28,resources=245,ordinary_terms=35)
 assert q['tests']['independent_DATA']['passed']==q['tests']['archive_option']['passed']==14
 assert q['root_admission_performed'] is False and q['financial_sessions_reexecuted']==0

def test_stopped_profiles_are_not_eligible_for_unchanged_retry():
 import system_campaign_control as control
 policy=json.loads((C/'system-campaign-control-policy.json').read_bytes());accepted={r['arm']:r for r in control.accepted_status()}
 for arm in ('P03','P07'):
  row=next(r for r in policy['next_events'] if r['arm']==arm)
  assert row['retry_authorized'] is False and 'profile_qualification' not in row
  assert control.qualified_profile(C,row,accepted[arm])==(False,'EVENT_PROFILE_NOT_QUALIFIED')

def test_financial_import_fences():
 for name in ('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'):
  assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
