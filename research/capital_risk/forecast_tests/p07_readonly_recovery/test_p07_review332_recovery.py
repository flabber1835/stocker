"""Pure source/quarantine metadata and explicit no-authority hook DTOs."""
import ast,json,sys,zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('P07_REVIEW332_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence())
P=Path(__file__).parent;C=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(P),str(C)]
import system_campaign_p07_readonly_review_recovery as recovery
import system_campaign_p07_historical_selector_review as selector
import system_campaign_financial_review_repair as original
import system_campaign_financial_future as future
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial326-source-snapshot/capture-P07-13480122074-001')
def ext(p):return Path(p) if str(p).startswith('\\\\?\\') else Path('\\\\?\\'+str(Path(p).resolve()))

@pytest.fixture
def target():return deepcopy(recovery.fact()['target'])

def request(t):
    return dict(EXPLICIT_NONCANONICAL_REQUEST_DTO=True,execution_mode=recovery.MODE,arms=['P07'],
        financial_resume_authorized=False,readonly_partial_review=True,readonly_source_witnesses=False,
        maximum_parallel_financial_workers=0,maximum_parallel_readonly_workers=1,
        **{recovery.FIELD:{'P07':recovery.declaration(t)}})

def test_actual_failed_transport_preserves_stops_and_grants_no_financial_authority(target):
    assert recovery.validate_target(target) is True
    assert target['prior_stops']['worker']['exit_code']==target['prior_stops']['reviewer']['exit_code']==1
    assert target['financial_authority'] is target['financial_predecessor_admitted'] is False
    assert target['review_sha256'] is None and 'root_admission' not in target
    recovery.request_only_readonly(request(target),target)

@pytest.mark.parametrize('change',['root','outer','count','input','descriptor','source','archive','stop','authority','log','marker'])
def test_exact_target_rejects_foreign_or_promoted_metadata(target,change):
    if change=='root':target['root_admission_sha256']='0'*64
    elif change=='outer':target['outer_sha256']='0'*64
    elif change=='count':target['measured_closes']=1278
    elif change=='input':target['input_sha256']='0'*64
    elif change=='descriptor':target['repairs'].pop()
    elif change=='source':target['source_binding_sha256']='0'*64
    elif change=='archive':target['zip_bytes']+=1
    elif change=='stop':target['prior_stops']['reviewer']['exit_code']=0
    elif change=='authority':target['financial_authority']=True
    elif change=='log':target['review_log_sha256']='0'*64
    else:target[recovery.MARKER]=False
    with pytest.raises(ValueError):recovery.validate_target(target)

def removed(module,name,label):
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(x,ast.Constant) and x.value==label for x in node.value.args):self.hits+=1;return None
            return self.generic_visit(node)
    mutation=Remove();fn=ast.fix_missing_locations(mutation.visit(fn));assert mutation.hits==1
    ns=dict(vars(module));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-readonly-recovery-DATA-guard>','exec'),ns);return ns[name]

def test_target_source_binding_guard_has_meaningful_removal(target):
    target['source_binding_sha256']='0'*64
    with pytest.raises(ValueError):recovery.validate_target(target)
    fn=removed(recovery,'validate_target','P07_REVIEW_ONLY_EXACT_FULL24_FAILED_TRANSPORT_NO_STATE_OR_AUTHORITY_SUBSTITUTION')
    assert fn(target) is True

def test_one_gib_case_guard_has_meaningful_removal(monkeypatch,target):
    target['zip_bytes']=1024**3+1;v=recovery.fact();v['target']=deepcopy(target)
    monkeypatch.setattr(recovery,'fact',lambda:v)
    with pytest.raises(ValueError,match='ONE_GIB_CRYPTO_OPTION'):recovery.validate_target(target)
    fn=removed(recovery,'validate_target','P07_REVIEW_EXACT_585_MEMBER_ONE_GIB_CRYPTO_OPTION_ONLY')
    assert fn(target) is True

def test_current_and_historical_definitions_and_existing_additive_qualification():
    assert selector.source_contract().name==selector.HISTORICAL
    assert future.sha(Path(future.__file__).read_bytes())==selector.CURRENT_SHA

def test_physical_selector_hash_guard_removal_accepts_foreign_same_AST_source(monkeypatch,tmp_path):
    raw=(selector.HERE/selector.HISTORICAL).read_bytes();(tmp_path/selector.HISTORICAL).write_bytes(raw+b'\n# foreign bytes\n')
    monkeypatch.setattr(selector,'HERE',tmp_path)
    with pytest.raises(ValueError,match='PHYSICAL_HISTORICAL_SELECTOR'):selector.source_contract()
    fn=removed(selector,'source_contract','P07_READONLY_EXACT_CURRENT_AND_PHYSICAL_HISTORICAL_SELECTOR_SOURCES')
    assert fn()==tmp_path/selector.HISTORICAL

def test_complete_quarantine_AST_undo_changes_only_case_constants_and_size_option():
    source=Path(original.__file__).read_bytes()
    for name in ('public_names','prove_refusal','admit','require_requalified_review'):
        before=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
        after=recovery.case_tree(name)
        old_trace=next((n.value for n in ast.walk(before) if isinstance(n,ast.Constant) and isinstance(n.value,bytes) and n.value.startswith(b'FileNotFoundError:')),None)
        class Undo(ast.NodeTransformer):
            def visit_Constant(self,node):
                value=node.value
                if name=='prove_refusal':
                    replacements={b'review_ordinary':b'ordinary_reconstruction',
                        b'ValueError: REFUSED_AUGMENTATION_REVIEW_COMPLETE_INPUT_AND_PACKET_RECONSTRUCTION':old_trace,
                        1238:1047,'P07_REVIEW_EXACT_DIAGNOSED_HISTORICAL_SELECTOR_REFUSAL':'REVIEW_REPAIR_EXACT_DIAGNOSED_MISSING_INPUT_REFUSAL',
                        'P07_REVIEW_ONLY_ORIGINAL1238_ACCOUNTING_REVIEW_EXISTS':'REVIEW_REPAIR_ONLY_OLD1047_ACCOUNTING_REVIEW_EXISTS'}
                    if value in replacements:return ast.copy_location(ast.Constant(replacements[value]),node)
                elif name=='require_requalified_review' and type(value) is int and value in (1259,21,784):
                    return ast.copy_location(ast.Constant({1259:1196,21:149,784:593}[value]),node)
                elif name=='admit' and value=='P07_REVIEW_ORIGINAL_FIN326_REQUEST_BYTES':return ast.copy_location(ast.Constant('REVIEW_REPAIR_ORIGINAL_FIN296_REQUEST_BYTES'),node)
                return node
            def visit_BinOp(self,node):
                if name=='admit' and ast.unparse(node)=='1024 ** 3':return ast.copy_location(ast.parse('512*1024**2',mode='eval').body,node)
                return self.generic_visit(node)
        after=ast.fix_missing_locations(Undo().visit(after));assert ast.dump(before)==ast.dump(after),name

def test_actual_failed_log_origin_and_original1238_accounting_metadata(target):
    inventory=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
    recovery.prove_refusal(target,inventory,ext(R/'verified-output'))
    with zipfile.ZipFile(ext(R/'artifact.zip')) as archive:names=recovery.public_names(target,archive)
    assert len(names)==5

def test_whole_review_lambda_code_and_closure_are_retained():
    def factory():return {}
    ns=dict(future_api=factory);exec('def review_ordinary(*args):\n return future_api(), args\n',ns)
    scope=dict(review_ordinary=ns['review_ordinary'])
    exec('def make(plan,phase,validate):\n return lambda *args: review_ordinary(*args,plan,phase,validate)\n',scope)
    old=scope['make']('PLAN_DTO','PHASE_DTO','VALIDATOR_DTO');new=selector.bind_review_lambda(old)
    assert new.__code__ is old.__code__ and new.__closure__ is old.__closure__
    assert new.__globals__ is not old.__globals__
    assert new.__globals__['review_ordinary'].__code__ is old.__globals__['review_ordinary'].__code__
    assert old.__globals__['review_ordinary'].__globals__['future_api'] is factory

def test_compiler_binding_changes_only_fresh_namespace():
    def make():
        ns={};exec('def hydrate(): pass\ndef document(): pass\ndef prepare(): pass\ndef review_input(): pass\n',ns);return ns
    before=future.__file__;first=selector.historical_factory(make)();second=selector.historical_factory(make)()
    assert first is not second and first['__file__']==second['__file__']==str(selector.HERE/selector.HISTORICAL)
    assert future.__file__==before and first['hydrate'].__globals__ is first

@pytest.mark.parametrize('mode',['launch','preflight','review'])
def test_readonly_scope_restores_every_hook_even_on_failure(monkeypatch,target,mode):
    import full_system_core,probe,system_campaign_p07_abmd_lifecycle as lifecycle
    monkeypatch.setattr(probe,'check_context',lambda env:None)
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);monkeypatch.setattr(recovery,'target',lambda:target)
    old=(original.applies,original.admit,original.ORIGIN,original.require_requalified_review,lifecycle.selected)
    with pytest.raises(RuntimeError,match='NONCANONICAL_ABORT'):
        with recovery.context(request(target),spec=target,mode=mode):
            assert original.ORIGIN==recovery.ORIGIN and original.applies(target)
            assert lifecycle.selected(target) is True
            raise RuntimeError('NONCANONICAL_ABORT')
    assert (original.applies,original.admit,original.ORIGIN,original.require_requalified_review,lifecycle.selected)==old

@pytest.mark.parametrize('change',['financial','economic','foreign_arm','missing_declaration'])
def test_no_economic_or_foreign_request_can_enter_scope(monkeypatch,target,change):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);monkeypatch.setattr(recovery,'target',lambda:target)
    r=request(target);mode='preflight'
    if change=='financial':r['financial_resume_authorized']=True
    elif change=='economic':mode='economic'
    elif change=='foreign_arm':r['arms']=['P05']
    else:r[recovery.FIELD]={}
    with pytest.raises(ValueError):
        with recovery.context(r,spec=target,mode=mode):pass

@pytest.mark.parametrize('which',['admit','context','selector'])
def test_hosted_guard_precedes_staging_or_runtime_hooks(monkeypatch,which):
    import full_system_core,probe
    def refuse():raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(full_system_core,'hosted',refuse)
    def refuse_launcher(env):raise ValueError('NOT_HOSTED')
    monkeypatch.setattr(probe,'check_context',refuse_launcher)
    with pytest.raises(ValueError,match='NOT_HOSTED'):
        if which=='admit':recovery.admit(None,None,None,None)
        elif which=='context':
            with recovery.context(None,mode='preflight'):pass
        else:
            with selector.context():pass

@pytest.mark.parametrize('name',['research.pooled_bad','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
    with pytest.raises(ImportError):__import__(name)

def test_actual_document_mismatch_is_only_the_historical_selector_and_hydration_hash():
    import gzip
    pins=json.loads((R/'authenticated-manifest.json').read_bytes())['members']
    def member(name):
        raw=ext(R/'verified-output'/name).read_bytes()
        assert dict(bytes=len(raw),sha256=future.sha(raw))==pins[name]
        return raw
    parent=json.loads(gzip.decompress(member('ordinary-augmentation/parent-checkpoint.json.gz')))
    name=future.hydration_name(parent)
    old_raw=member('ordinary-augmentation/'+name)
    new_raw=member('stopped-review/independent-ordinary-augmentation/'+name)
    old,new=json.loads(old_raw),json.loads(new_raw)
    assert [k for k in old if old[k]!=new[k]]==['selector_sha256']
    assert (old['selector_sha256'],new['selector_sha256'])==(selector.OLD_SHA,selector.CURRENT_SHA)
    original=json.loads(member('ordinary-augmentation/future-financial-overlay.json'))
    rebuilt=json.loads(member('stopped-review/independent-ordinary-augmentation/future-financial-overlay.json'))
    assert future.document(parent,old,future.sha(old_raw))==original
    assert future.document(parent,new,future.sha(new_raw))==rebuilt
    assert [k for k in original if original[k]!=rebuilt[k]]==['source_evidence']
    assert [i for i,(a,b) in enumerate(zip(original['source_evidence'],rebuilt['source_evidence'])) if a!=b]==[4,5]
    assert member('ordinary-augmentation/future-input-qualification.json')==member('stopped-review/independent-ordinary-augmentation/future-input-qualification.json')

def test_launch_wrapper_calls_whole_original_once_inside_readonly_scope(monkeypatch,tmp_path,target):
    import full_system_core,probe
    monkeypatch.setattr(probe,'check_context',lambda env:None)
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);monkeypatch.setattr(recovery,'target',lambda:target)
    path=tmp_path/'NONCANONICAL_READONLY_REQUEST_DTO.json';path.write_bytes(recovery.encoded(request(target)));calls=[]
    def body(args):
        assert original.ORIGIN==recovery.ORIGIN;calls.append(args.arm);return 777
    before=original.ORIGIN
    assert recovery.bind_launch(body)(SimpleNamespace(request=path,arm='P07'))==777
    assert calls==['P07'] and original.ORIGIN==before

def test_economic_scope_guard_has_meaningful_removal_without_running_a_worker(monkeypatch,target):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None);monkeypatch.setattr(recovery,'target',lambda:target)
    with pytest.raises(ValueError,match='ECONOMIC_MODE_FORBIDDEN'):
        with recovery.context(request(target),spec=target,mode='economic'):pass
    broken=removed(recovery,'context','P07_REVIEW_ECONOMIC_MODE_FORBIDDEN')
    with broken(request(target),spec=target,mode='economic'):
        assert original.ORIGIN==recovery.ORIGIN

def test_fresh_compiler_namespace_guard_has_meaningful_removal():
    # Explicitly unrelated metadata functions never contain financial code.
    def make():
        result={}
        for name in ('hydrate','document','prepare','review_input'):
            separate={};exec('def '+name+'(): pass\n',separate);result[name]=separate[name]
        return result
    with pytest.raises(ValueError,match='FRESH_COMPLETE_COMPILER_NAMESPACE'):selector.historical_factory(make)()
    fn=next(n for n in ast.parse(Path(selector.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='historical_factory')
    inner=next(n for n in fn.body if isinstance(n,ast.FunctionDef) and n.name=='factory')
    guards=[n for n in inner.body if isinstance(n,ast.Expr) and 'P07_READONLY_FRESH_COMPLETE_COMPILER_NAMESPACE_NOT_GLOBAL_MODULE' in ast.unparse(n)]
    assert len(guards)==1;inner.body.remove(guards[0]);scope=dict(vars(selector))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-fresh-private-namespace-guard>','exec'),scope)
    assert scope['historical_factory'](make)()['__file__']==str(selector.HERE/selector.HISTORICAL)
