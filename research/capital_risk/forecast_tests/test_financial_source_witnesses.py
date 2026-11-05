"""New frozen-source captures are DATA only; no canonical financial imports."""
import ast
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_resume as m


def source_fixture():
    native = dict(session='2022-07-21', security_id='synthetic', kind='CASH_MERGER', cash_per_share=None)
    row = dict(session='2022-07-20', security_id='synthetic', ticker='TEST', issuer_id='SOURCE:unchanged',
               listing_first_session='2012-01-03', security_type_eligible='1', raw_close='200.01')
    positions = [dict(slot_id=6, ticker='TEST', quantity=29, entry_date='2022-06-30')]
    term = dict(session=row['session'], security_id=row['security_id'], ticker='TEST',
                native_session=native['session'], native_term_sha256=f.digest(native), parent_positions=positions)
    scope = dict(parent_outer_sha256='a'*64, parent_cursor='2022-06-30', terms=[term])
    cp = dict(sha256='a'*64, source_cursor='2022-06-30', base=dict(archive_sha256='b'*64,bundle_sha256='c'*64),
        run=dict(state=dict(wealth_core=dict(episodes={'6':dict(slot_id=6, ticker='TEST',current_shares=29,
            entry_date='2022-06-30',security_id='synthetic')}))))
    return cp,scope,[native],[row]


def spec(cp):
    return dict(arm='P04',outer_sha256=cp['sha256'],selected_session=cp['source_cursor'],base=cp['base'])


def test_complete_row_native_and_actual_parent_scope_preserved_without_state_mutation():
    cp,scope,natives,rows=source_fixture();before=deepcopy((cp,scope,natives,rows))
    value=f.witness_payload(cp,'P04',scope,natives,rows)
    assert f.validate_witness_capture(value,spec(cp),scope)==value
    assert value['terms'][0]['source_row']==rows[0]
    assert value['terms'][0]['identity_witness']['source_observation_sha256']==f.digest(rows[0])
    assert value['terms'][0]['native_term']==natives[0]
    assert value['terms'][0]['parent_positions']==scope['terms'][0]['parent_positions']
    assert value['financial_sessions_advanced']==0 and value['financial_authority'] is value['input_adopted'] is False
    assert (cp,scope,natives,rows)==before


def test_ineligible_unknown_source_metadata_is_captured_without_upgrade():
    cp,scope,natives,rows=source_fixture()
    rows[0].update(issuer_id='SEC_UNKNOWN:synthetic',security_type_eligible='0')
    value=f.witness_payload(cp,'P04',scope,natives,rows)
    assert value['terms'][0]['source_row']==rows[0]
    assert value['terms'][0]['identity_witness']['security_type_eligible']=='0'
    assert value['provider_metadata_upgraded'] is False


@pytest.mark.parametrize('change', ['missing','duplicate','ticker','sid','eligible','listing','native','native_day',
                                   'quantity','entry_date','parent_hash','parent_cursor','future_consumed'])
def test_wrong_source_or_own_parent_scope_refuses(change):
    cp,scope,natives,rows=source_fixture()
    if change=='missing':rows.clear()
    elif change=='duplicate':rows.append(deepcopy(rows[0]))
    elif change=='ticker':rows[0]['ticker']='OTHER'
    elif change=='sid':rows[0]['security_id']='OTHER'
    elif change=='eligible':rows[0]['security_type_eligible']='2'
    elif change=='listing':rows[0]['listing_first_session']='2023-01-01'
    elif change=='native':natives[0]['cash_per_share']=203.
    elif change=='native_day':natives[0]['session']='2022-07-22'
    elif change=='quantity':cp['run']['state']['wealth_core']['episodes']['6']['current_shares']=28
    elif change=='entry_date':cp['run']['state']['wealth_core']['episodes']['6']['entry_date']='2022-06-29'
    elif change=='parent_hash':cp['sha256']='d'*64
    elif change=='parent_cursor':cp['source_cursor']='2022-07-01'
    else:scope['parent_cursor']=cp['source_cursor']='2022-07-21'
    with pytest.raises(ValueError):f.witness_payload(cp,'P04',scope,natives,rows)


@pytest.mark.parametrize('change',['raw_row','native','position','archive','producer','scope','authority','advance','input'])
def test_export_payload_cannot_change_bindings_or_gain_authority(change):
    cp,scope,natives,rows=source_fixture();value=f.witness_payload(cp,'P04',scope,natives,rows)
    if change=='raw_row':value['terms'][0]['source_row']['raw_close']='200.02'
    elif change=='native':value['terms'][0]['native_term']['cash_per_share']=203.
    elif change=='position':value['terms'][0]['parent_positions'][0]['quantity']=28
    elif change=='archive':value['archive_sha256']='0'*64
    elif change=='producer':value['producer_sha256']='0'*64
    elif change=='scope':value['scope_sha256']='0'*64
    elif change=='authority':value['financial_authority']=True
    elif change=='advance':value['financial_sessions_advanced']=1
    else:value['input_adopted']=True
    with pytest.raises(ValueError):f.validate_witness_capture(value,spec(cp),scope)


def test_parent_position_guard_removal_falsifier():
    cp,scope,natives,rows=source_fixture();cp['run']['state']['wealth_core']['episodes']['6']['current_shares']=28
    with pytest.raises(ValueError):f.witness_payload(cp,'P04',scope,natives,rows)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='source_terms')
    loop=next(n for n in fn.body if isinstance(n,ast.For))
    guard=next(n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and any(isinstance(a,ast.Constant) and a.value=='SOURCE_WITNESS_EXACT_PARENT_POSITION_SCOPE' for a in n.value.args))
    loop.body.remove(guard);ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-parent-position-guard>','exec'),ns)
    terms=ns['source_terms'](scope,natives,rows,[[dict(scope['terms'][0]['parent_positions'][0],quantity=28)]])
    assert terms[0]['parent_positions'][0]['quantity']==28


@pytest.mark.parametrize('kind',['identity','native','parent','capture','reconstruction'])
def test_source_binding_guard_removal_falsifiers(kind):
    cp,scope,natives,rows=source_fixture()
    payload=f.witness_payload(cp,'P04',scope,natives,rows)
    if kind=='identity':
        name,code='source_terms','SOURCE_WITNESS_EXACT_UNMODIFIED_IDENTITY'
        rows[0]['ticker']='OTHER'
        args=(scope,natives,rows,[scope['terms'][0]['parent_positions']])
    elif kind=='native':
        name,code='source_terms','SOURCE_WITNESS_EXACT_INCOMPLETE_NATIVE'
        natives[0]['cash_per_share']=203.
        args=(scope,natives,rows,[scope['terms'][0]['parent_positions']])
    elif kind=='parent':
        name,code='witness_payload','SOURCE_WITNESS_EXACT_OWN_PARENT'
        cp['sha256']='d'*64;args=(cp,'P04',scope,natives,rows)
    else:
        name='validate_witness_capture'
        code='SOURCE_WITNESS_EXACT_SOURCE_ONLY_CAPTURE' if kind=='capture' else 'SOURCE_WITNESS_FULL_PAYLOAD_RECONSTRUCTION'
        if kind=='capture':payload['archive_sha256']='0'*64
        else:payload['terms'][0]['source_row']['raw_close']='200.02'
        args=(payload,spec(cp),scope)
    with pytest.raises(ValueError):getattr(f,name)(*args)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value==code for a in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=remove.visit(fn);assert remove.count==1
    ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-source-binding-guard>','exec'),ns)
    assert ns[name](*args)


def test_closed_source_scopes_keep_exact_historical_own_parents():
    from system_campaign_financial_partial import root_spec
    assert set(f.HISTORICAL_WITNESS_SCOPES)=={'P04','P10'}
    for arm,scope in f.HISTORICAL_WITNESS_SCOPES.items():
        terms=json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())['terms']
        term,=[t for t in terms if t['arm']==arm and t['parent_cursor']==scope['parent_cursor']]
        root=root_spec(arm,term['parent_root_admission_sha256'])
        assert root['outer_sha256']==scope['parent_outer_sha256'] and root['selected_session']==scope['parent_cursor']
    assert f.HISTORICAL_WITNESS_SCOPES['P04']['terms'][0]['parent_positions'][0]['quantity']==29
    assert f.HISTORICAL_WITNESS_SCOPES['P10']['terms'][0]['parent_positions']==[]


@pytest.mark.parametrize('flags',list(product([False,True],repeat=3)))
def test_exactly_one_authority_mode_is_required(flags):
    modes=['OWN_ADMITTED_FINANCIAL_CONTINUATION','READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION',
           'READONLY_FROZEN_SOURCE_WITNESSES']
    request=dict(zip(('financial_resume_authorized','readonly_partial_review','readonly_source_witnesses'),flags))
    request['execution_mode']=modes[flags.index(True)] if any(flags) else modes[0]
    assert m.request_authority(request) is (sum(flags)==1)
    request['execution_mode']='UNKNOWN'
    assert m.request_authority(request) is False


def test_boolean_integer_does_not_grant_authority():
    request=dict(financial_resume_authorized=False,readonly_partial_review=False,readonly_source_witnesses=1,
                 execution_mode='READONLY_FROZEN_SOURCE_WITNESSES')
    assert m.request_authority(request) is False


def test_stopped_source_capture_never_launches_financial_workers(tmp_path,monkeypatch):
    from research.capital_risk.forecast_tests.test_financial_resume import launch_fixture
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'witness')
    assert m.launch(args)==0 and calls==['preflight'] and len(exports)==1
    receipt=json.loads(args.output.read_bytes())
    assert receipt['status']=='SOURCE_WITNESSES_HOSTED_CAPTURED_PENDING_DATA'
    assert receipt['financial_resume_authorized'] is receipt['readonly_partial_review'] is False
    assert receipt['readonly_source_witnesses'] is True and 'worker' not in receipt and 'reviewer' not in receipt


def test_corrupt_source_payload_cannot_trigger_finance_or_report_success(tmp_path,monkeypatch):
    from research.capital_risk.forecast_tests.test_financial_resume import launch_fixture
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'witness-bad-payload')
    assert m.launch(args)==2 and calls==['preflight'] and len(exports)==1
    assert json.loads(args.output.read_bytes())['status']=='REFUSED_STOPPED_EVIDENCE_PRESERVED'


def test_unknown_source_worker_has_no_export(tmp_path,monkeypatch):
    from research.capital_risk.forecast_tests.test_financial_resume import launch_fixture
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'witness-unknown-preflight')
    assert m.launch(args)==2 and calls==['preflight'] and exports==[]
    assert 'encrypted_output' not in json.loads(args.output.read_bytes())


def capture_fixture(tmp_path,monkeypatch,mutate=False):
    from contextlib import nullcontext
    from dataclasses import make_dataclass
    from types import ModuleType,SimpleNamespace
    cp,scope,natives,rows=source_fixture();calls=[]
    Native=make_dataclass('Native',[(k,object) for k in natives[0]])
    actions=SimpleNamespace(terminal={scope['terms'][0]['native_session']:(Native(**natives[0]),)})
    def load(path):
        calls.append(('actions',path.as_posix()));return actions
    def scan(archive,name):
        calls.append(('annual',name))
        if mutate:cp['synthetic_unrelated_marker']='changed'
        yield dict(rows[0],security_id='unrequested')
        yield rows[0]
    module=ModuleType('research.pooled_input_support')
    module.inputs=SimpleNamespace(load_actions=load,_archive_rows=scan)
    monkeypatch.setitem(sys.modules,'research.pooled_input_support',module)
    monkeypatch.setattr(f,'hosted',lambda:None)
    monkeypatch.setattr(f.zipfile,'ZipFile',lambda path:nullcontext(object()))
    return cp,scope,calls


def test_hosted_capture_scans_declared_year_once_and_exports_exact_row_only(tmp_path,monkeypatch):
    cp,scope,calls=capture_fixture(tmp_path,monkeypatch)
    before=deepcopy(cp);value=f.capture_source_witnesses(cp,tmp_path,'P04',scope)
    assert cp==before and calls==[('actions','/frozen/bundle'),('annual','observations-2022.csv.gz')]
    assert len(value['terms'])==1 and value['terms'][0]['source_row']['security_id']=='synthetic'
    assert json.loads((tmp_path/f.SOURCE_WITNESS_FILE).read_bytes())==value


def test_capture_parent_state_guard_removal_falsifier(tmp_path,monkeypatch):
    cp,scope,calls=capture_fixture(tmp_path,monkeypatch,mutate=True)
    with pytest.raises(ValueError,match='PARENT_STATE_UNCHANGED'):f.capture_source_witnesses(cp,tmp_path,'P04',scope)
    assert not (tmp_path/f.SOURCE_WITNESS_FILE).exists()
    cp.pop('synthetic_unrelated_marker')
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='capture_source_witnesses')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and any(isinstance(a,ast.Constant) and a.value=='SOURCE_WITNESS_PARENT_STATE_UNCHANGED' for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-source-parent-state-guard>','exec'),ns)
    assert ns['capture_source_witnesses'](cp,tmp_path,'P04',scope)
    assert cp['synthetic_unrelated_marker']=='changed'


def test_root_preflight_runs_source_capture_without_repeating_reporting_or_finance(tmp_path,monkeypatch):
    from research.capital_risk.forecast_tests.test_financial_retention import preflight_fixture
    old,out,selected,calls=preflight_fixture(tmp_path,monkeypatch)
    selected['root_admission']={};monkeypatch.setattr(m,'validate_root_spec',lambda spec:None)
    request=dict(financial_resume_authorized=False,readonly_partial_review=False,readonly_source_witnesses=True,
                 execution_mode='READONLY_FROZEN_SOURCE_WITNESSES',source_witness_scopes={'P04':{'synthetic':True}})
    Path(m.REQUEST).write_text(json.dumps(request))
    monkeypatch.setattr(m,'source_request_bindings',lambda actual,spec: None if actual==request and spec is selected else (_ for _ in ()).throw(AssertionError('wrong request/root')))
    monkeypatch.setattr(m,'expected_request',lambda:(_ for _ in ()).throw(AssertionError('workflow lookup inside worker')))
    captures=[]
    monkeypatch.setattr(f,'capture_source_witnesses',lambda cp,target,arm,scope:captures.append(
        (cp['sha256'],target,arm,scope)))
    m.preflight(old,out,selected)
    assert calls==[] and captures==[('a'*64,out,'P04',{'synthetic':True})]
    assert json.loads((out/'strict-parent-preflight.json').read_bytes())['financial_sessions_advanced']==0
    assert (out/'source-witness-request.json').read_bytes()==Path(m.REQUEST).read_bytes()


def qualified_worker_request(monkeypatch):
    selected=m.root_spec('P05','a19ff05c0685ab37fc886c3ddcde7b958e083b60af9904087ba1822937a65078')
    monkeypatch.setattr(m,'root_spec',lambda arm:selected if arm=='P05' else None)
    monkeypatch.setattr(f,'WITNESS_SCOPES',{'P05':deepcopy(f.EXTRA_WITNESS_SCOPES['P05','2020-11-30'])})
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_FROZEN_SOURCE_WITNESSES')
    monkeypatch.setattr(m,'SELECTED_ARMS',('P05',))
    request=m.expected_request();m.source_request_bindings(request,selected)
    return request,selected


def test_worker_checks_exact_source_bindings_without_accessing_host_workflow(monkeypatch):
    request,selected=qualified_worker_request(monkeypatch)
    monkeypatch.setattr(m,'expected_request',lambda:(_ for _ in ()).throw(AssertionError('host-only workflow lookup')))
    m.source_request_bindings(request,selected)


@pytest.mark.parametrize('change',['schema','mode','scope','root','bundle','launcher','selector'])
def test_changed_worker_request_binding_refuses(change,monkeypatch):
    request,selected=qualified_worker_request(monkeypatch)
    if change=='schema':request['schema']='UNKNOWN'
    elif change=='mode':request['financial_resume_authorized']=True
    elif change=='scope':request['source_witness_scopes']['P05']['terms'][0]['ticker']='OTHER'
    elif change=='root':request['admitted_checkpoints']['P05']='0'*64
    elif change=='bundle':request['admitted_financial_parents_sha256']='0'*64
    elif change=='launcher':request['sources']['system_campaign_financial_resume.py']='0'*64
    else:request['sources']['system_campaign_financial_future.py']='0'*64
    with pytest.raises(ValueError):m.source_request_bindings(request,selected)


def test_worker_source_binding_guard_removal_falsifier(monkeypatch):
    request,selected=qualified_worker_request(monkeypatch)
    request['sources']['system_campaign_financial_resume.py']='0'*64
    with pytest.raises(ValueError):m.source_request_bindings(request,selected)
    fn=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='source_request_bindings')
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call))]
    ns=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-worker-source-request-guard>','exec'),ns)
    assert ns['source_request_bindings'](request,selected) is None


def test_different_actual_worker_request_cannot_be_accepted(tmp_path,monkeypatch):
    from research.capital_risk.forecast_tests.test_financial_resume import launch_fixture
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'witness-wrong-request')
    assert m.launch(args)==2 and calls==['preflight'] and len(exports)==1
    assert json.loads(args.output.read_bytes())['status']=='REFUSED_STOPPED_EVIDENCE_PRESERVED'


def test_actual_worker_request_byte_guard_removal_falsifier(tmp_path,monkeypatch):
    from research.capital_risk.forecast_tests.test_financial_resume import launch_fixture
    args,calls,exports=launch_fixture(tmp_path,monkeypatch,'witness-wrong-request')
    fn=next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='launch')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(a,ast.Constant) and
               a.value=='RESUME_SOURCE_WITNESS_ACTUAL_WORKER_REQUEST_BYTES' for a in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=remove.visit(fn);assert remove.count==1
    ns=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-actual-worker-request-byte-guard>','exec'),ns)
    assert ns['launch'](args)==0 and calls==['preflight']


def test_closed_source_scope_cannot_silently_follow_a_newer_admitted_root(monkeypatch):
    monkeypatch.setattr(m,'COMPLETED_ADMISSIONS',{})
    monkeypatch.setattr(f,'WITNESS_SCOPES',{'P10':deepcopy(f.NEXT_WITNESS_SCOPES['P10'])})
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_FROZEN_SOURCE_WITNESSES')
    monkeypatch.setattr(m,'SELECTED_ARMS',('P10',))
    request=m.expected_request();current=m.root_spec('P10')
    closed=f.HISTORICAL_WITNESS_SCOPES['P10']
    assert current['outer_sha256']!=closed['parent_outer_sha256']
    request['source_witness_scopes']['P10']=deepcopy(closed)
    with pytest.raises(ValueError,match='EXACT_WORKER_REQUEST_BINDINGS'):
        m.source_request_bindings(request,current)


def test_registry_preserves_original_fresh_p00_and_current_own_queries():
    assert set(f.WITNESS_SCOPES)==set(f.ACTIVE_WITNESS_SCOPES)=={'P00','P03','P07','P04','P05','P06','P11'}
    for arm,quantity in [('P05',25),('P06',17),('P11',35)]:
        scope=f.RESOLVED_TENDER_WITNESS_SCOPES[arm]
        assert scope==f.registered_scope(f.digest(scope))
        from research.capital_risk.forecast_tests.test_financial_initial_prefix import initial_entry
        assert scope['parent_outer_sha256']==m.root_spec(arm,initial_entry(arm)['admission_sha256'])['outer_sha256']
        term,=scope['terms']
        assert (term['ticker'],term['security_id'])==('AAAP1','554122275008038119')
        assert term['parent_positions'][0]['quantity']==quantity
        assert term['session']=='2018-01-31' and term['native_session']=='2018-02-09'
    assert len(f.WITNESS_SCOPE_REGISTRY)==41
    scope=f.NEXT_WITNESS_SCOPES['P00'];root=m.root_spec('P00','c08cec7a7dc2b9fe84f9318c81b2874f25ae45fd9126f80e00deee70ee3f4694');term,=scope['terms']
    assert scope==f.registered_scope(f.digest(scope))
    assert (scope['parent_outer_sha256'],scope['parent_cursor'])==(root['outer_sha256'],'2018-08-31')
    assert term['ticker']=='ILG' and term['parent_positions'][0]['quantity']==90
    assert term['pending_at_parent']['pending_sessions']==0
    assert scope['additional_rows'][0]['ticker']=='VAC' and scope['additional_rows'][0]['parent_positions']==[]
    terms=json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())['terms']
    for t in terms:
        retained=f.registered_scope(t['source_capture']['scope_sha256'])
        assert retained['parent_outer_sha256']==t['parent_outer_sha256']
        expected=(f.research_mixed_term(t) if t['recognition_rule']==f.RESEARCH_MIXED else
                  f.selected_stock_term(t) if t['added']['kind']=='CASH_PLUS_STOCK' else t)
        assert f.own_cash_selection(t['arm'],t['parent_cursor'])[2]==[expected]


def test_current_fresh_p00_tgi_query_uses_only_own1883_root_and_actual234_shares():
    scope=f.WITNESS_SCOPES['P00'];root=m.root_spec('P00');term,=scope['terms']
    assert scope==f.registered_scope(f.ACTIVE_WITNESS_SCOPES['P00'])
    assert root['measured_closes']==1883 and root['selected_session']==scope['parent_cursor']=='2025-06-30'
    assert root['outer_sha256']==scope['parent_outer_sha256']
    assert term['ticker']=='TGI' and term['session']=='2025-07-23' and term['native_session']=='2025-07-24'
    assert term['parent_positions']==[dict(slot_id=2,ticker='TGI',quantity=234,entry_date='2025-04-04')]
    assert root['root_admission']['initial_fresh_origin_root_admission_sha256']=='c08cec7a7dc2b9fe84f9318c81b2874f25ae45fd9126f80e00deee70ee3f4694'


def test_p11_edr_query_uses_new169_root_and_one_actual_share():
    scope=f.EXTRA_WITNESS_SCOPES['P11','2018-08-31']
    original=next(t for t in json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())['terms'] if t['ticker']=='EDR1')
    root=m.root_spec('P11',original['parent_root_admission_sha256']);term,=scope['terms']
    assert scope==f.registered_scope(f.digest(scope))
    assert root['measured_closes']==169 and scope['parent_cursor']==root['selected_session']=='2018-08-31'
    assert scope['parent_outer_sha256']==root['outer_sha256']
    assert (term['ticker'],term['security_id'])==('EDR1','371238123781729047')
    assert term['parent_positions']==[dict(slot_id=4,ticker='EDR1',quantity=1,entry_date='2018-08-31')]
    assert term['session']=='2018-09-18' and term['native_session']=='2018-09-19'


def test_p11_tvty_query_binds_only_own1111_and_never_backdates_later134_shares():
    original=next(t for t in json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())['terms']
                  if (t['arm'],t['parent_cursor'])==('P11','2022-05-31'))
    scope=f.EXTRA_WITNESS_SCOPES['P11','2022-05-31'];root=m.root_spec('P11',original['parent_root_admission_sha256']);term,=scope['terms']
    assert scope==f.registered_scope(f.digest(scope))
    assert root['measured_closes']==1111 and scope['parent_cursor']==root['selected_session']=='2022-05-31'
    assert scope['parent_outer_sha256']==root['outer_sha256']
    assert (term['ticker'],term['security_id'],term['session'],term['native_session'])==('TVTY','506048722516044547','2022-06-27','2022-06-28')
    assert term['parent_positions']==[] and term['native_term_sha256'] is None
    assert f.source_schema(scope)==f.SOURCE_WITNESS_DISCOVERY_SCHEMA
    assert scope['native_preimage_query']['financial_use_authorized'] is False


def test_p03_arii_query_binds_only_own232_and_exact_frozen_native():
    scope=f.EXTRA_WITNESS_SCOPES['P03','2018-11-30'];root=m.root_spec('P03','84381db5458891e421209047b2933c8182c981ccc106743ab5f9ca946fa135a7');term,=scope['terms']
    assert scope==f.registered_scope('cafac06fa7fce92009e528bfdcfb2cb4dc9a7e5719b69edfb9e5f8737f6813e2')
    assert root['measured_closes']==232 and scope['parent_cursor']==root['selected_session']=='2018-11-30'
    assert scope['parent_outer_sha256']==root['outer_sha256']
    assert term==dict(ticker='ARII',security_id='435766160247494711',session='2018-12-03',
        native_session='2018-12-04',native_term_sha256='4447441e01411420775c471f8c54d01fe6f00d54adaff997517b0d360cad8222',parent_positions=[])
    assert f.source_schema(scope)==f.SOURCE_WITNESS_SCHEMA


def test_p03_send_scope_binds_own251_and_exact_additional_twlo_row():
    scope=f.EXTRA_WITNESS_SCOPES['P03','2018-12-31'];root=m.root_spec('P03','a89d9976ab0621b14d921fe9079784d62d835d9634b9ed423d66060d925eb3cd')
    assert f.digest(scope)=='2a49277ae3ac10ffec90fa984691f2b9b511ccc3e8f5073f3f4f64168a07c6dd'
    assert scope==f.registered_scope(f.digest(scope))
    assert (root['measured_closes'],root['selected_session'])==(251,'2018-12-31')
    assert root['outer_sha256']==scope['parent_outer_sha256'] and f.source_schema(scope)==f.SOURCE_WITNESS_PENDING_SCHEMA
    assert scope['terms'][0]['ticker']=='SEND' and scope['terms'][0]['parent_positions']==[]
    assert scope['additional_rows']==[dict(ticker='TWLO',security_id='361746987237610562',session='2019-02-01',
        source_observation_sha256='9d1d9eeb1363f4226fa7789a982a35ec3bb738f92d65a398b1208aca68df1107',parent_positions=[])]


def test_p07_lm_query_binds_only_new628_root_and_its_actual_parent_holding(monkeypatch):
    scope=f.NEXT_WITNESS_SCOPES['P07'];root=m.root_spec('P07','2293655ea9e4c520c66e016a33c9d33b78f12ceb09c50a371bc84b76c0eef543');term,=scope['terms']
    assert scope==f.registered_scope(f.digest(scope))
    assert root['measured_closes']==628 and root['selected_session']==scope['parent_cursor']=='2020-06-30'
    assert root['outer_sha256']==scope['parent_outer_sha256']
    assert term['ticker']=='LM' and term['session']=='2020-07-29' and term['native_session']=='2020-07-30'
    assert term['parent_positions']==[dict(slot_id=20,ticker='LM',quantity=49,entry_date='2020-06-24')]
    monkeypatch.setattr(m,'SELECTED_ARMS',('P07',))
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_FROZEN_SOURCE_WITNESSES')
    assert m.expected_request()['financial_resume_authorized'] is False


@pytest.mark.parametrize('change',['unknown','mutated'])
def test_unknown_or_changed_registered_scope_refuses(monkeypatch,change):
    scopes=deepcopy(f.WITNESS_SCOPE_REGISTRY);key=f.ACTIVE_WITNESS_SCOPES['P00']
    if change=='unknown':key='0'*64
    else:scopes[key]['terms'][0]['parent_positions']=[dict(quantity=78)]
    monkeypatch.setattr(f,'WITNESS_SCOPE_REGISTRY',scopes)
    with pytest.raises(ValueError,match='EXACT_REGISTERED_SCOPE_DIGEST'):f.registered_scope(key)


def test_registered_scope_digest_guard_removal_falsifier(monkeypatch):
    scopes=deepcopy(f.WITNESS_SCOPE_REGISTRY);key=f.ACTIVE_WITNESS_SCOPES['P00']
    scopes[key]['parent_cursor']='2022-08-30';monkeypatch.setattr(f,'WITNESS_SCOPE_REGISTRY',scopes)
    with pytest.raises(ValueError):f.registered_scope(key)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='registered_scope')
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call))]
    ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-registered-scope-digest>','exec'),ns)
    assert ns['registered_scope'](key)['parent_cursor']=='2022-08-30'
