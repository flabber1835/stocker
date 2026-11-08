"""Actual admitted DATA and finite source/AST falsifiers; no canonical execution."""
import ast,gzip,json,sys
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
import pytest
D=Path('C:\\GitHub\\stocker\\.codex-tmp\\p03-own524-14cash18-prep-20261106');C=Path(__file__).resolve().parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('P03_CASH14_TEST_DATA_ONLY:'+name)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_cash14_data as data
import system_campaign_p03_cash14_api as api
import system_campaign_p03_cash14_lifecycle as life
import system_campaign_p03_cash14_runtime as runtime
import system_campaign_p03_cash14_stage as stage
from system_campaign_financial_partial import root_spec
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
@pytest.fixture(scope='module')
def actual():
    cap=R/'financial340-P03-source-snapshot/capture-P03-13525097150-001';root=Path('\\\\?\\'+str((cap/'verified-output').resolve()))
    mf=json.loads((cap/'authenticated-manifest.json').read_bytes())['members']
    def member(n):
        raw=(root/n).read_bytes();assert dict(bytes=len(raw),sha256=data.sha(raw))==mf[n];return raw
    cp=life.strict_json(member('book/checkpoint.json.gz'));spec=root_spec('P03',data.ROOT)
    proof=member('uncertainty-certificate.jsonl');lines=proof.splitlines(keepends=True);rows=[json.loads(v) for v in lines[:70]]
    return SimpleNamespace(root=root,member=member,cp=cp,spec=spec,rows=rows,proof=proof)
def test_exact_current524_and_original70_seed(actual):
    f=data.parent_contract(actual.cp,actual.spec)
    assert (len(actual.cp['repairs']),f['branch_proof']['rows'],f['branch_proof']['retained_rows'])==(17,21,49)
    assert dict(rows=70,bytes=len(runtime.reuse.seed_bytes(actual.rows)),sha256=data.sha(runtime.reuse.seed_bytes(actual.rows)))==f['retained_seed']
    assert len(actual.proof.splitlines())==81 and all(json.loads(v)['session']>'2020-01-31' for v in actual.proof.splitlines()[70:])
def test_all_fourteen_terms_and_original_constructors():
    terms=data.terms();assert len(terms)==14 and terms[0]['ticker']=='DERM2'
    assert len(data.supplemental()[1])==4 and data.PrimaryCash(data.primary_catalog()).catalog['parent_root_admission_sha256']==data.old.ROOT
    assert {t['ticker'] for t in terms}=={'DERM2','BEAT1','VRTU','ACIA','VAR','MIK','FPRX','GNMK','GLUU','WIFI','CATM','NAV','HOME','PFPT'}
    assert all(t['added']['kind']=='CASH_MERGER' for t in terms)
    assert all(t['retained_qualified_source']['originating_book_authority_retained'] is False for t in terms)
    assert (D/data.CATALOG).read_bytes()==data.encoded(data.catalog())
def test_full_source_namespaces_never_relabel_current_role():
    a,b=data.source('SOURCE327'),data.source('SOURCE334')
    assert a['payload']['parent_cursor']==b['payload']['parent_cursor']=='2019-12-31'
    assert a['payload']['scope_sha256']!=b['payload']['scope_sha256'] and len(a['payload']['terms'])==len(b['payload']['terms'])==128
    c=data.catalog();assert c['current_root_admission_sha256']==data.ROOT and c['old503_roles_are_current524_roles'] is False
@pytest.mark.parametrize('change',['price','date','source_row','native','preopen'])
def test_DERM_primary_original_validator_guards(change):
    value=data.primary_catalog();term=value['terms'][0]
    if change=='price':term['added']['cash_per_share']=18.74
    elif change=='date':term['added']['session']='2020-02-19'
    elif change=='source_row':term['identity_witness']['security_type_eligible']='1'
    elif change=='native':term['native_term_sha256']='0'*64
    else:term['preopen_completion_confirmed']=False
    with pytest.raises(ValueError):data.validate_primary(value)
def test_existing19_observers_reaudited_without_future_state(actual):
    assert len(runtime.observers(actual.root,actual.cp,19))==19
    with pytest.raises(ValueError):runtime.observers(actual.root,actual.cp,33)
def test_no_real_neutral18_invented_for_seed(actual):
    with pytest.raises(ValueError,match='ONLY_REAL_NEUTRAL18'):runtime.seed_contract(actual.rows,actual.cp,actual.spec)
@pytest.mark.parametrize('name',life.FUNCTIONS)
def test_whole_lifecycle_AST_undo(name):
    tree=life.body_tree(name)
    if name=='boundary_relation':
        maps={"terms = value['terms']":"term, = value['terms']",
            "doc['add'] == [t['added'] for t in terms]":"doc['add'] == [term['added']]",
            "doc['suppress'] == [dict(session=t['native_session'], security_id=t['security_id'], term_sha256=t['native_term_sha256']) for t in terms]":"doc['suppress'] == [dict(session=term['native_session'],security_id=data.SID,term_sha256=term['native_term_sha256'])]",
            "adoption(neutral, parent, data.sha(raw), min((t['native_session'] for t in terms)))":"adoption(neutral,parent,data.sha(raw),term['native_session'])"}
        class UndoBatch(ast.NodeTransformer):
            hits=set()
            def visit(self,node):
                s=ast.unparse(node)
                if s in maps:
                    self.hits.add(s);return ast.copy_location(ast.parse(maps[s]).body[0] if isinstance(node,ast.stmt) else ast.parse(maps[s],mode='eval').body,node)
                return super().visit(node)
        u=UndoBatch();tree=u.visit(tree);assert u.hits==set(maps)
    ints={v:k for k,v in life.INTS.items()};strings={v:k for k,v in (life.DATES|life.STRINGS).items()}
    class UndoFinite(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is int and node.value in ints:node.value=ints[node.value]
            elif type(node.value) is str and node.value in strings:node.value=strings[node.value]
            return node
    tree=UndoFinite().visit(tree)
    assert ast.dump(tree,include_attributes=False)==ast.dump(life.source_tree(name),include_attributes=False)
def test_all_whole_original_API_code_objects(actual):
    bound=api.api(actual.cp,actual.spec)
    assert bound.whole_original_hydrate.__code__ is api.original.hydrate.__code__
    for name in ('document','qualify','prepare','review_input','source_scopes'):
        assert getattr(bound,name).__code__ is getattr(api.original,name).__code__
def test_complete_real_factual_document_includes82_evidence_records(actual):
    bound=api.api(actual.cp,actual.spec);codec=bound.selected('P03',cursor='2020-01-31')[0]
    material=dict(catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,
        selector_sha256=data.sha(Path(api.__file__).read_bytes()),terms=data.terms(),ordinary_components=data.supplemental()[1])
    # This is pure document/schema DATA, not a fabricated provider receipt or
    # a selected canonical repair. Hosted prepare will supply the real material.
    document=bound.document(actual.cp,material,data.sha(data.encoded(material)))
    assert len(document['add'])==len(document['suppress'])==14 and len(document['source_evidence'])==82<=128
    assert {v['session'] for v in document['add'] if v['security_id']==data.SID}=={'2020-02-20'}
    assert {v['session'] for v in document['suppress'] if v['security_id']==data.SID}=={'2020-02-19'}
def test_full_original_provider_stage_code_and_mount_parser_undo():
    assert stage.provider_stage_function().__code__ is stage.ORIGINAL_STAGE.__code__
    raw=Path(stage.prior.__file__).read_bytes();old=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='preflight_worker_old');tree=stage.worker_tree()
    class Undo(ast.NodeTransformer):
        def visit_Constant(self,n):
            if n.value=='capital-system-resume-p03-preflight-':n.value='capital-system-resume-p05-preflight-'
            elif n.value=='financial-resume-preflight-P03':n.value='financial-resume-preflight-P05'
            return n
    assert ast.dump(Undo().visit(tree),include_attributes=False)==ast.dump(old,include_attributes=False)
def test_actual_complete_pinned_provider_alias_object():
    path=R/'financial340-P05-source-snapshot/capture-P05-13524003871-001/verified-output/provider-source/SHARADAR_ACTIONS.zip'
    path=Path('\\\\?\\'+str(path.resolve()))
    proof=api.provider(path)
    assert proof['BEAT1_original_rows']==5 and proof['provider_bytes']==9855560 and proof['metadata_upgraded'] is False
def test_finite_request_selects_new_root_and_leaves_old_thor_route(monkeypatch,actual):
    monkeypatch.setattr(runtime,'qualification',lambda:'UNIT_TEST_ONLY_NOT_A_REAL_QUALIFICATION')
    original=lambda:dict(admitted_checkpoints={'P03':data.OUTER},arm_inputs={'P03':dict(new_factual_overlay=False)},sources={})
    result=runtime.expected_thor_request(original,execution_mode=runtime.MODE,selected_arms=('P03',),root_lookup=lambda a:actual.spec)
    assert result[life.original.FIELD]=={} and result['arm_inputs']['P03']['new_factual_overlay'] is True
    declared=runtime.declaration(actual.spec)
    request=dict(execution_mode=runtime.MODE,financial_resume_authorized=True,readonly_partial_review=False,readonly_source_witnesses=False,**{runtime.FIELD:{'P03':declared}})
    assert runtime.request_selected(actual.spec,request)
    for key in ('readonly_partial_review','readonly_source_witnesses'):
        wrong=deepcopy(request);wrong[key]=True;assert not runtime.request_selected(actual.spec,wrong)
    assert not runtime.selected(dict(arm='P03',root_admission_sha256='b8cf6b7fcc737daf21870dd9cce4874910d3f33139c92201d0c4ae730ea33e43'))
def test_whole_original_exclusive_qualification_writer_undo():
    changed=runtime.run_tree();original=life.typed.body_tree('run_retained')
    i=next(i for i,n in enumerate(changed.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='qualification_was_present')
    originalwrite=changed.body[i+1].body[0];changed.body[i:i+3]=[deepcopy(originalwrite)]
    assert ast.dump(changed,include_attributes=False)==ast.dump(original,include_attributes=False)
def test_parent_commitment_guard_removal_is_meaningful(actual):
    wrong=deepcopy(actual.cp);wrong['completed']+=1
    with pytest.raises(ValueError):data.parent_contract(wrong,actual.spec)
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='parent_contract')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='P03_14_ONLY_ACTUAL_ADMITTED524_FULL17_ALL_COMMITMENTS' for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-actual-parent-guard-DATA-only>','exec'),ns)
    assert ns['parent_contract'](wrong,actual.spec)['root_admission_sha256']==data.ROOT
def test_neutral70_guard_removal_is_meaningful(actual):
    fn=next(n for n in ast.parse(Path(runtime.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='seed_contract')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='P03_14_ONLY_REAL_NEUTRAL18_AND_EXACT70_ADMITTED_SEED' for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(runtime));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-real-neutral-seed-guard-DATA-only>','exec'),ns)
    with pytest.raises(ValueError):runtime.seed_contract(actual.rows,actual.cp,actual.spec)
    assert ns['seed_contract'](actual.rows,actual.cp,actual.spec)['rows']==70
def test_whole_fact_source_guard_removal_is_meaningful(tmp_path,monkeypatch):
    fact=data.facts()
    for name in fact['source_files']:(tmp_path/name).write_bytes((D/name).read_bytes())
    wrong=deepcopy(fact);wrong['expected_total_observer_terms']=32;(tmp_path/data.FACT).write_bytes(data.encoded(wrong))
    monkeypatch.setattr(data,'HERE',tmp_path)
    with pytest.raises(ValueError,match='EXACT_FINITE_ACTUAL524_FACTS'):data.facts()
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='facts')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='P03_14_EXACT_FINITE_ACTUAL524_FACTS' for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-whole-fact-source-guard-DATA-only>','exec'),ns)
    assert ns['facts']()['expected_total_observer_terms']==32
@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_all_five_import_fences(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
