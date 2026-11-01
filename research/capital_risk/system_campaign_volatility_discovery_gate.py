"""Hosted retention equivalence; every original risk refusal remains enabled."""
import ast,gzip,json
from copy import deepcopy
from pathlib import Path
from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import sha,digest
from system_campaign_parallel_discovery import compile_body
import system_campaign_risk_discovery_gate as original

HERE=Path(__file__).parent
PRIOR='system-campaign-risk-discovery-request-002.json'
PRIOR_SHA='368b2a778dcb6823df94d93a1327b4d3962ce1e04e8028717cb24c3f5f9e54fd'

def corrected_tree(mode):
    need(mode in ('FAST','REFERENCE'),'V_RETENTION_ONLY_DECLARED_EXECUTION_MODES')
    request=(HERE/PRIOR).read_bytes();need(sha(request)==PRIOR_SHA,'V_RETENTION_EXACT_FAILED_REQUEST')
    raw=Path(original.__file__).read_bytes()
    need(sha(raw)==json.loads(request)['sources'][Path(original.__file__).name],
         'V_RETENTION_ORIGINAL_GATE_UNCHANGED')
    tree=ast.parse(raw);calls=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and ast.unparse(node.func)=='Execution':
            need(len(node.args)==1 and isinstance(node.args[0],ast.Constant) and node.args[0].value=='FAST'
                 and len(node.keywords)==1 and node.keywords[0].arg=='signal_closes'
                 and isinstance(node.keywords[0].value,ast.Constant) and node.keywords[0].value.value==1,
                 'V_RETENTION_EXACT_OLD_ONE_CLOSE_CONFIGURATION')
            node.args[0].value=mode;node.keywords[0].value.value=127;calls.append(node)
    need(len(calls)==2,'V_RETENTION_TWO_QUALIFICATION_EXECUTION_SITES_ONLY')
    return tree

def compiled_gate(mode):
    scope=dict(vars(original))
    exec(compile(ast.fix_missing_locations(corrected_tree(mode)),
        '<source-bound-volatility-retention-gate>','exec'),scope)
    return scope['qualify']

def qualify(root,parent,out,*,selected_file,source_iterator,code):
    hosted()
    from research.pooled_vacancy_funding import runtime
    out=Path(out);out.mkdir(exist_ok=True);paths={};proofs={}
    for mode in ('FAST','REFERENCE'):
        target=out/mode.lower();target.mkdir()
        records=[];advance=runtime.advance
        def observed(run,published):
            result=advance(run,published)
            records.append(dict(session=published.session,publication_sha256=digest(published),
                                checkpoint=runtime.checkpoint(result)))
            return result
        runtime.advance=observed
        try:
            compiled_gate(mode)(root,parent,target,selected_file=selected_file,
                                source_iterator=source_iterator,code=code)
            need(runtime.advance is observed,'V_RETENTION_INNER_RUNTIME_HOOK_RESTORED')
        finally:runtime.advance=advance
        need(len(records)==3,'V_RETENTION_THREE_ACTUAL_SUCCESSFUL_CANONICAL_SESSIONS')
        paths[mode]=records
        proofs[mode]=json.loads((target/'discovery-canonical-qualification.json').read_bytes())
        with gzip.open(target/'actual-runtime-path.json.gz','xb') as f:
            f.write((json.dumps(records,sort_keys=True,separators=(',',':'))+'\n').encode())
    need(paths['FAST']==paths['REFERENCE'],'V_RETENTION_ALL_ACTUAL_PUBLISHED_AND_RUNTIME_VALUES_EQUAL')
    need(proofs['FAST']==proofs['REFERENCE'],'V_RETENTION_ALL_ACTUAL_QUALIFICATION_EVENTS_EQUAL')
    proof=deepcopy(proofs['FAST'])
    proof.update(signal_material_closes=127,actual_fast_reference_full_runtime_paths_equal=True,
                 actual_fast_reference_published_sessions_equal=True,
                 canonical_runtime_path_sha256=digest(paths['FAST']),
                 financial_source_or_risk_rule_changed=False)
    save(out/'discovery-canonical-qualification.json',proof)
