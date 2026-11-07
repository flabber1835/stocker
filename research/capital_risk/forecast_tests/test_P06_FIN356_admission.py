"""Exact metadata admission and retained failed/positive evidence separation."""
import json,sys
from pathlib import Path
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
import system_campaign_financial_partial as p

def test_new_P06_root_is_exact1677_full12_and_preserves_prior_root():
 current=p.root_spec('P06');old=p.root_spec('P06','edfe96119e6f8bf833e54189452698bca2bfca65676e2d0a861bb6a9ea69bf0f')
 assert (current['measured_closes'],current['selected_session'],len(current['repairs']))==(1677,'2024-08-30',12)
 assert (old['measured_closes'],old['selected_session'],len(old['repairs']))==(1426,'2023-08-31',11)
 assert current['repairs'][:11]==old['repairs'] and current['base']==old['base']
 a=current['root_admission'];assert a['parent_root_admission_sha256']==old['root_admission_sha256']
 assert (a['new_daily_records'],a['independent_accounting_snapshots'],a['new_monthly_reports'])==(251,502,12)
 assert a['branch_uncertainty_proof']['rows']==251 and a['branch_uncertainty_proof']['retained_rows']==173
 assert a['source_input_proof']['full_inputs']==12 and a['source_input_proof']['all89_resources_verified'] is True

def test_failed_financial_receipt_and_separate_positive_review_are_preserved():
 spec=p.root_spec('P06');a=spec['root_admission']
 assert spec['receipt_status']==a['original_failed_financial_receipt_status']=='FINANCIAL_REVIEW_REFUSED_PRESERVED'
 assert [spec['prior_stops'][r]['exit_code'] for r in ('preflight','worker','reviewer')]==[0,1,1]
 assert a['original_failed_financial_receipt_preserved'] is True and a['original_failed_financial_receipt_sha256']==spec['receipt_sha256']
 q=a['fresh_readonly_financial_review_requalification']
 assert q['passed'] is q['original_failed_stops_preserved'] is True and q['financial_sessions_advanced']==0
 assert q['original_financial_artifact_id']==13581395529 and q['original_review359_artifact']==13581834378
 assert q['original_review359_run_id']==a['readonly_run_id']==42392468427
 assert a['local_canonical_runtime_executed'] is a['production_contacted'] is a['performance_scoring_authorized'] is False

def test_new_root_does_not_select_an_unqualified_future_financial_worker():
 import system_campaign_financial_resume as resume
 import system_campaign_p06_WWE12_runtime as old_profile
 assert resume.SELECTED_ARMS==() and old_profile.candidate(p.root_spec('P06')) is False
