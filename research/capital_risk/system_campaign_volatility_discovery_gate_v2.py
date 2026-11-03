"""One source-bound recorder correction for typed publications."""
import ast,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_discovery_context import digest as publication_digest
from system_campaign_parallel_discovery import compile_body
import system_campaign_volatility_discovery_gate as original

HERE=Path(__file__).parent
PRIOR='system-campaign-p01-accurate-request-001.json'
PRIOR_SHA='70cb685834aa55378375978e97fac0d012729aa0586f7f18ea9fede9925aa8f8'

def recorder_tree():
    raw=(HERE/PRIOR).read_bytes();need(sha(raw)==PRIOR_SHA,'V_RECORDER_EXACT402_PRIOR_REQUEST')
    code=Path(original.__file__).read_bytes()
    need(sha(code)==json.loads(raw)['sources'][Path(original.__file__).name],'V_RECORDER_ORIGINAL_FAILED_SOURCE_RETAINED')
    fn,=[n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name=='qualify']
    calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n)=='digest(published)']
    need(len(calls)==1,'V_RECORDER_ONE_TYPED_PUBLICATION_DIGEST_SITE')
    calls[0].func=ast.Name(id='publication_digest',ctx=ast.Load())
    return fn

def qualify(*args,**kwargs):
    return compile_body(recorder_tree(),dict(vars(original),publication_digest=publication_digest))(*args,**kwargs)
