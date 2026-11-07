"""Exact full25 readonly reporting and explicit hosted copy equivalence."""
import ast,json,os,re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import system_campaign_p07_lossless_export as loss
import system_campaign_p07_abmd_lifecycle as life
import system_campaign_p07_vivo_runtime as runtime
import system_campaign_p07_vivo_api as visitor
import system_campaign_p07_vivo_profile as vivo
HERE=Path(__file__).parent
FACT='P07-FIN343-full25-reporting-fact-v2.json'
PIN='785a38fc180271536bcb50c086b6e7c78f6fa4ac4b3c18ef49b0d4b9c78f8223'
MARKER='p07_fin343_full25_reporting'
FIELD='selected_p07_full25_readonly_reporting'
MODE='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
ROOT='d9c73a5ceebdc806feeae4338034626c0c3b4aef42309f3849d69c20cfbf8f7b'
need,sha,encoded=loss.need,loss.sha,loss.encoded
def fact():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==PIN,'REPORT25_EXACT_FACT');return json.loads(raw)
def selected(spec):return isinstance(spec,dict) and spec.get(MARKER) is True
def validate(spec):need(encoded(spec)==encoded(fact()['target']),'REPORT25_ONLY_AUTHENTIC_UNADMITTED1383_FULL25')
def declaration(spec):
    validate(spec);return dict(fact_sha256=PIN,target_outer_sha256=spec['outer_sha256'],completed=1383,full_inputs=25,old_completed=1259,new_rows=124,financial_authority=False)
def require_request(request,spec):
    validate(spec);need(request['execution_mode']==MODE and request['arms']==['P07'] and request['financial_resume_authorized'] is False
        and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
        and request['maximum_parallel_financial_workers']==0 and request['maximum_parallel_readonly_workers']==1
        and request.get(FIELD)=={'P07':declaration(spec)},'REPORT25_EXPLICIT_ZERO_FINANCIAL_REQUEST')
def source_names():return (Path(__file__).name,FACT)
def expected_vivo_request(original,*,execution_mode,selected_arms,root_lookup):
    if execution_mode==MODE and list(selected_arms)==['P07']:
        target=json.loads((HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P07']
        if selected(target):
            validate(target);need(root_lookup('P07')['root_admission_sha256']==ROOT,'REPORT25_EXACT_ORIGINAL_MONTHLY_ROOT')
            return vivo.expected_request(original,execution_mode=execution_mode,selected_arms=(),root_lookup=root_lookup)
    return vivo.expected_request(original,execution_mode=execution_mode,selected_arms=selected_arms,root_lookup=root_lookup)
def expected_request(original,*,execution_mode,selected_arms,target_lookup):
    value=original();value[FIELD]={}
    if execution_mode==MODE and list(selected_arms)==['P07'] and selected(target_lookup('P07')):
        value[FIELD]['P07']=declaration(target_lookup('P07'));value['arm_inputs']['P07']['new_factual_overlay']=False
    for n in source_names():
        pin=sha((HERE/n).read_bytes());need(n not in value['sources'] or value['sources'][n]==pin,'REPORT25_NO_SOURCE_PIN_REPLACEMENT');value['sources'][n]=pin
    return value
def host_guard():
    from probe import check_context
    check_context(os.environ)
def reconstruct(root,manifest):
    """Only hosted, authenticated redundant bytes; never locally called on a book."""
    host_guard();root=Path(root).resolve();before,_=loss.inventory(root)
    need(before==manifest,'REPORT25_EXACT_PHYSICAL_SOURCE_BEFORE_EXPANSION')
    def physical(n):return (root/n).read_bytes()
    logical=loss.logical_members(physical,manifest);created=[];dirs=[]
    try:
        for item in logical.representation['copies']:
            name=loss.safe_name(item['name']);path=root/name;need(path.resolve().is_relative_to(root) and not path.exists(),'REPORT25_FRESH_OWNED_COPY_PATH')
            parents=[p for p in path.parents if p!=root and p.is_relative_to(root) and not p.exists()]
            for p in reversed(parents):p.mkdir();dirs.append(p)
            raw=logical(name)
            with path.open('xb') as f:created.append(path);f.write(raw)
        expected=dict(logical.representation['before_inventory']);expected[loss.RECEIPT]=manifest[loss.RECEIPT]
        need(loss.inventory(root)[0]==expected,'REPORT25_ALL_LOGICAL_BYTES_PRESENT_NO_UNIQUE_SOURCE_CHANGE')
    except Exception:
        for p in reversed(created):p.unlink()
        for p in reversed(dirs):p.rmdir()
        need(loss.inventory(root)[0]==before,'REPORT25_FAILED_EXPANSION_EXACT_ROLLBACK');raise
    return dict(passed=True,physical_files=len(manifest),logical_files=len(expected),copies=len(created),checkpoint_changed=False,financial_sessions_advanced=0)
def bind_launch(original,module):
    def launch(args):
        request=json.loads(Path(args.request).read_bytes())
        if args.arm!='P07' or not request.get(FIELD):return original(args)
        target=json.loads((HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P07'];require_request(request,target);host_guard()
        import system_campaign_p07_fin326_requalified_parent as composite
        old_admit,old_applies=module.admit_partial,composite.applies
        def admit(spec,*a,**k):
            stage='CRYPTO_ADMISSION'
            try:
                result=old_admit(spec,*a,**k)
                if selected(spec):
                    stage='LOGICAL_EXPANSION';validate(spec);reconstruct(result,fact()['physical_manifest'])
                return result
            except Exception as exc:
                value=dict(p07_readonly_stage=stage,error_type=type(exc).__name__)
                if isinstance(exc,ValueError) and re.fullmatch('[A-Z0-9_]{1,200}',str(exc)):value['guard']=str(exc)
                if isinstance(exc,KeyError) and len(exc.args)==1 and re.fullmatch('[a-z_]{1,64}',str(exc.args[0])):value['field']=str(exc.args[0])
                print(json.dumps(value),flush=True);raise
        composite.applies=lambda spec:False if spec.get('root_admission_sha256')==ROOT else old_applies(spec)
        module.admit_partial=admit
        try:return original(args)
        finally:module.admit_partial,composite.applies=old_admit,old_applies
    return launch
@contextmanager
def entry_context(module,spec,*,mode,request):
    from full_system_core import hosted
    hosted();require_request(request,spec);need(mode=='preflight','REPORT25_ONLY_READONLY_PREFLIGHT_NO_FINANCIAL_ENTRY')
    expected=fact()['original4_AST'];actual={n.name:loss.digest(ast.dump(n,include_attributes=False)) for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in expected}
    need(actual==expected,'REPORT25_FOUR_ORIGINAL_FINANCIAL_BODIES')
    from system_campaign_financial_partial import root_spec
    origin=root_spec('P07',ROOT);old_api=life.api
    def deny(*a,**k):raise ValueError('REPORT25_FINANCIAL_CALLBACK_FORBIDDEN')
    def api(root,current,target):
        if not selected(target):return old_api(root,current,target)
        validate(target)
        need((current['sha256'],len(current['repairs'])) in ((spec['outer_sha256'],25),(origin['outer_sha256'],24)), 'REPORT25_ONLY_ACTUAL_CURRENT_OR_ORIGINAL_MONTHLY_SEED')
        visitor.full_models(root,current)
        value=runtime.api(root,current,origin)
        return SimpleNamespace(**dict(vars(value),run=deny,review=deny,run_retained=deny,review_retained=deny))
    life.api=api
    try:
        with life.entry(spec):yield
    finally:life.api=old_api
