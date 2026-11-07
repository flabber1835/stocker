"""Actual W metadata import and exact whole-module code identity; no function execution."""
import hashlib,json,sys
from pathlib import Path
P=Path(__file__).resolve().parent
C=Path('C:/GitHub/stocker/.codex-tmp/wealth-variants-complete-20261105/research/capital_risk')
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_V2_ACTUAL_IMPORT_METADATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path[:0]=[str(P),str(C)]
import system_campaign_financial_resume as actual
import system_campaign_p07_lossless_export_host as v2
assert Path(v2.__file__).resolve().parent==P
raw=(C/'system-campaign-factual-request.json').read_bytes();request=json.loads(raw)
seal,stop=v2.bound_sources(actual,request)
stale=dict(request,sources=dict(request['sources']))
stale['sources']['system_campaign_financial_resume.py']='f'*64
try:v2.bound_sources(actual,stale)
except ValueError as exc:assert str(exc)=='P07_LOSSLESS_EXACT_HOST_DRIVER_SOURCE'
else:raise AssertionError('STALE_ACTUAL_HOST_SOURCE_REQUEST_WAS_NOT_REFUSED')
original_need=v2.need
def without_host_owner(value,label):
    if label!='EXACT_HOST_DRIVER_SOURCE':original_need(value,label)
v2.need=without_host_owner
try:assert v2.bound_sources(actual,stale)==(seal,stop)
finally:v2.need=original_need
spec=actual.root_spec('P07')
assert spec['root_admission_sha256']==v2.ROOT and spec['measured_closes']==1259 and len(spec['repairs'])==24
print(json.dumps(dict(passed=True,actual_imported_module_file=actual.__file__,v2_host_module_file=v2.__file__,
    actual_request_sha256=hashlib.sha256(raw).hexdigest(),original_seal_code_exact=True,original_stop_code_exact=True,
    stale_actual_request_refused=True,meaningful_actual_host_source_owner_guard_removal=True,
    physical_module_sources_and_function_global_owners_exact=True,financial_runtime_executed=False,
    canonical_function_body_executed=False,hosted_job_launched=False,existing_request_requalified_for_v2=False)))
