"""Exact FIN326 P07 quarantine and complete original readonly requalification."""
import ast,json,os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from system_campaign_facts import sha
from full_system_benchmark import need

HERE=Path(__file__).parent
FACT='P07-FIN326-readonly-recovery-fact-v1.json'
FACT_SHA='77c14f042c326798c2d6e00c7db898184262407ab6b109dcbba01cbd9e6424c5'
MARKER='p07_fin326_readonly_review_recovery'
FIELD='selected_p07_failed_review_recoveries'
FLAG='readonly_failed_review_requalification'
MODE='READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
ORIGIN='475af771e38bc5bb9600bdf0031fbb1036304a5e36348dc82cf8fbac4497098d'
OUTER='1e1e4dbce5a3b13c329bfb2c16a99e6f6043bcc8628a9852971f7100d9295a3a'
LEGACY_SHA='9d4d9e938685926838e229f05f064803137f47d53bfdacf406bee7a1bffcfa5e'
RUN=42165076736
HEAD='485894f4c5d6aa5b1373ccd843ff083e3f15bf33'
ARTIFACT=13480122074
STATUS='FINANCIAL_REVIEW_REFUSED_PRESERVED'
ARM='P07'

def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()

def fact():
    raw=(HERE/FACT).read_bytes();need(sha(raw)==FACT_SHA,'P07_REVIEW_EXACT_FIN326_METADATA_FACT_BYTES')
    value=json.loads(raw);scope=value['scope']
    need(value['original_root_admission_sha256']==ORIGIN and value['original_root_completed']==1238
         and value['original_root_inputs']==23 and value['expected_new_rows']==21 and value['expected_retained_rows']==784
         and scope['readonly_repair_only'] is True and scope['financial_resume_authorized'] is scope['input_adopted']
             is scope['financial_root_admitted'] is scope['diagnostic_state_adopted'] is False,
         'P07_REVIEW_ONLY_ORIGINAL1238_AND_UNADMITTED1259_METADATA')
    return value

def applies(spec):return isinstance(spec,dict) and spec.get(MARKER) is True

def validate_target(spec):
    need(applies(spec) and encoded(spec)==encoded(fact()['target']),
         'P07_REVIEW_ONLY_EXACT_FULL24_FAILED_TRANSPORT_NO_STATE_OR_AUTHORITY_SUBSTITUTION')
    need(spec.get(FLAG) is True and 'root_admission' not in spec and 'root_admission_sha256' not in spec
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
         and spec['review_sha256'] is None and spec['receipt_status']==STATUS
         and spec['measured_closes']==1259 and len(spec['repairs'])==24
         and spec['zip_bytes']==770361099 and spec['manifest']==dict(member_count=585,raw_member_bytes=964176783)
         and spec['manifest']['raw_member_bytes']<1024**3,
         'P07_REVIEW_EXACT_585_MEMBER_ONE_GIB_CRYPTO_OPTION_ONLY')
    return True

def declaration(spec):
    validate_target(spec)
    return dict(schema='research.P07-FIN326-readonly-review-recovery/1',arm='P07',
        original_root_admission_sha256=ORIGIN,target_outer_sha256=OUTER,target_completed=1259,target_inputs=24,
        original_financial_artifact_id=ARTIFACT,original_financial_run_id=RUN,original_financial_head=HEAD,
        fact_file=FACT,fact_sha256=FACT_SHA,historical_selector_sha256=fact()['historical_selector_sha256'],
        expected_new_rows=21,expected_retained_rows=784,financial_workers=0,financial_resume_authorized=False,
        input_adopted=False,financial_root_admitted=False,original_failed_stops_preserved=True)

def request_only_readonly(request,spec):
    validate_target(spec)
    need(request['execution_mode']==MODE and request['arms']==['P07'] and request['financial_resume_authorized'] is False
         and request['readonly_partial_review'] is True and request['readonly_source_witnesses'] is False
         and request['maximum_parallel_financial_workers']==0 and request['maximum_parallel_readonly_workers']==1
         and request.get(FIELD)=={'P07':declaration(spec)},'P07_REVIEW_EXPLICIT_ZERO_FINANCIAL_REQUEST_ONLY')

def source_names():
    import system_campaign_p07_historical_selector_review as selector
    from system_campaign_p07_abmd_lifecycle import source_names as original
    return tuple(sorted(set(original())|{Path(__file__).name,Path(selector.__file__).name,selector.HISTORICAL,FACT}))

def target():return json.loads((HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P07']

def selected_request(request):
    if request.get(FIELD,{}).get('P07') is None:return False
    request_only_readonly(request,target());return True

def expected_request(original,*,execution_mode,selected_arms,target_lookup):
    result=original();selected={}
    if execution_mode==MODE and list(selected_arms)==['P07']:
        candidate=target_lookup('P07')
        if applies(candidate):selected['P07']=declaration(candidate)
    result[FIELD]=selected
    for name in source_names():
        pin=sha((HERE/name).read_bytes());need(name not in result['sources'] or result['sources'][name]==pin,
            'P07_REVIEW_NO_SOURCE_PIN_REPLACEMENT');result['sources'][name]=pin
    return result

def case_tree(name):
    import system_campaign_financial_review_repair as original
    raw=Path(original.__file__).read_bytes();need(sha(raw)==LEGACY_SHA,'P07_REVIEW_WHOLE_ORIGINAL_FAILED_REVIEW_ADAPTER')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    class Case(ast.NodeTransformer):
        def visit_Constant(self,node):
            value=node.value
            if name=='prove_refusal':
                if value==b'ordinary_reconstruction':return ast.copy_location(ast.Constant(b'review_ordinary'),node)
                if isinstance(value,bytes) and value.startswith(b'FileNotFoundError:'):
                    return ast.copy_location(ast.Constant(b'ValueError: REFUSED_AUGMENTATION_REVIEW_COMPLETE_INPUT_AND_PACKET_RECONSTRUCTION'),node)
                if type(value) is int and value==1047:return ast.copy_location(ast.Constant(1238),node)
                if value=='REVIEW_REPAIR_EXACT_DIAGNOSED_MISSING_INPUT_REFUSAL':return ast.copy_location(ast.Constant('P07_REVIEW_EXACT_DIAGNOSED_HISTORICAL_SELECTOR_REFUSAL'),node)
                if value=='REVIEW_REPAIR_ONLY_OLD1047_ACCOUNTING_REVIEW_EXISTS':return ast.copy_location(ast.Constant('P07_REVIEW_ONLY_ORIGINAL1238_ACCOUNTING_REVIEW_EXISTS'),node)
            elif name=='require_requalified_review' and type(value) is int:
                if value in (1196,149,593):return ast.copy_location(ast.Constant({1196:1259,149:21,593:784}[value]),node)
            elif name=='admit' and value=='REVIEW_REPAIR_ORIGINAL_FIN296_REQUEST_BYTES':
                return ast.copy_location(ast.Constant('P07_REVIEW_ORIGINAL_FIN326_REQUEST_BYTES'),node)
            return node
        def visit_BinOp(self,node):
            if name=='admit' and ast.unparse(node)=='512 * 1024 ** 2':
                return ast.copy_location(ast.parse('1024**3',mode='eval').body,node)
            return self.generic_visit(node)
    return ast.fix_missing_locations(Case().visit(fn))

def bound(name):
    import system_campaign_financial_review_repair as original
    scope=dict(vars(original),validate_target=validate_target,request_only_readonly=request_only_readonly,
        public_names=public_names,prove_refusal=prove_refusal,ORIGIN=ORIGIN,OUTER=OUTER,RUN=RUN,HEAD=HEAD,ARM=ARM,ARTIFACT=ARTIFACT,STATUS=STATUS)
    fn=case_tree(name);exec(compile(ast.Module(body=[fn],type_ignores=[]),'<whole-original-readonly-quarantine-exact-FIN326-case>','exec'),scope)
    return scope[name]

def public_names(spec,archive):return bound('public_names')(spec,archive)
def prove_refusal(spec,inventory,root):return bound('prove_refusal')(spec,inventory,Path(root))
def launcher_guard():
    from probe import check_context
    check_context(os.environ)
def admit(spec,root,key,inspector):
    launcher_guard();return bound('admit')(spec,root,key,inspector)
def require_requalified_review(root,spec):return bound('require_requalified_review')(root,spec)

@contextmanager
def context(request,*,spec=None,mode):
    from full_system_core import hosted
    if mode=='launch':launcher_guard()
    else:hosted()
    need(mode in ('launch','preflight','review'),'P07_REVIEW_ECONOMIC_MODE_FORBIDDEN')
    need(selected_request(request),'P07_REVIEW_EXACT_ACTIVE_READONLY_REQUEST_REQUIRED')
    import system_campaign_financial_review_repair as original
    import system_campaign_p07_abmd_lifecycle as lifecycle
    from system_campaign_financial_partial import root_spec,validate_root_spec
    from system_campaign_p07_historical_selector_review import context as historical
    origin=root_spec('P07',ORIGIN);validate_root_spec(origin)
    need(origin['outer_sha256']==fact()['original_root_outer_sha256'],'P07_REVIEW_GENUINE_ORIGINAL1238_AUTHORITY')
    if spec is not None:
        if applies(spec):validate_target(spec)
        else:need(spec==origin,'P07_REVIEW_ONLY_EXACT_TARGET_OR_ORIGINAL_REVIEW_PARENT')
    saved={n:getattr(original,n) for n in ('applies','admit','ORIGIN','require_requalified_review')}
    chosen=lifecycle.selected
    original.applies=lambda value:applies(value) or saved['applies'](value)
    original.admit=lambda value,*a,**k:admit(value,*a,**k) if applies(value) else saved['admit'](value,*a,**k)
    original.ORIGIN=ORIGIN
    original.require_requalified_review=lambda root,value:require_requalified_review(root,value) if applies(value) else saved['require_requalified_review'](root,value)
    def selected(value,request=None):
        if value==origin:return True
        if applies(value):validate_target(value);return True
        return chosen(value,request)
    lifecycle.selected=selected
    try:
        if mode=='review':
            with historical():yield
        else:yield
    finally:
        lifecycle.selected=chosen
        for name,value in saved.items():setattr(original,name,value)

def bind_launch(original):
    def launch(args):
        check=original.__globals__.get('check_context')
        if check is None:
            from probe import check_context as check
        check(os.environ)
        request=json.loads(Path(args.request).read_bytes())
        if not selected_request(request):return original(args)
        need(args.arm=='P07','P07_REVIEW_LAUNCH_ONLY_EXACT_SELECTED_ARM')
        with context(request,mode='launch'):return original(args)
    return launch
