"""Closed source pins and independent per-arm job scheduling; DATA only."""
import json,sys
from pathlib import Path
import pytest,yaml
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('SGN_REQUEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_financial_resume as financial
import system_campaign_source_exit_entry as p
from system_campaign_financial_partial import root_spec

def test_closed232_request_selects_only_genuine2050_P06_and_all_source_bytes():
 request=financial.expected_request();spec=root_spec('P06')
 assert request==json.loads((C/financial.REQUEST).read_bytes()) and financial.request_authority(request)
 assert request['schema'].endswith('/232') and request['arms']==['P06']
 assert request['admitted_checkpoints']=={'P06':spec['outer_sha256']}
 assert request['maximum_parallel_financial_workers']==1 and request['maximum_parallel_readonly_workers']==0
 assert p.runtime.request_financial(request,spec) is True
 declaration=request[p.runtime.FIELD]['P06']
 assert declaration['committed_seed_rows']==797 and declaration['required_neutral_inputs']==15
 assert declaration['actual_neutral_checkpoint_known'] is declaration['held_settlement_authorized'] is False
 assert declaration['actual_constructor_required_before_finance'] is True
 for name,pin in request['sources'].items():assert p.sha((C/name).read_bytes())==pin
 request['sources']['system_campaign_source_exit_future_acquisition.py']='f'*64
 with pytest.raises(ValueError,match='ALL_CURRENT_SOURCE_PINS'):p.runtime.request_financial(request,spec)

def test_new_P06_job_keeps_per_arm_queue_and_does_not_select_or_cancel_live_P07():
 workflow=yaml.load((C.parents[1]/'.github/workflows/capital-system-campaign-factual-suffix.yml').read_bytes(),Loader=yaml.BaseLoader)
 job=workflow['jobs']['suffix']
 assert job['strategy']['matrix']['arm']==['P06'] and job['strategy']['max-parallel']=='4'
 assert job['concurrency']['group'].endswith('$'+'{{ matrix.arm }}') and job['concurrency']['cancel-in-progress']=='false'
 source=yaml.load((C.parents[1]/'.github/workflows/capital-system-source-batch.yml').read_bytes(),Loader=yaml.BaseLoader)
 assert not set(workflow['on']['push']['paths'])&set(source['on']['push']['paths'])
