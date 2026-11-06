"""Actual own1132 source metadata and guard-removal falsifiers; DATA only."""
import ast,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('PENDING_SOURCE_QUERY_DATA_ONLY:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(Path(__file__).parent))
import system_campaign_pending_native_source_queries_v2 as data
from system_campaign_financial_partial import root_spec

def actual():return json.loads((data.HERE/data.CATALOG).read_bytes())

def test_actual_source_scope_keeps_held35_native_pending0_and_original_query_unchanged():
    import system_campaign_explicit_source_queries as original
    old=(original.HERE/original.CATALOG).read_bytes()
    scope=data.selected_scopes({},['P05'],enabled=True,root_lookup=root_spec)['P05'];term,=scope['terms']
    assert scope['parent_cursor']==term['native_session']=='2022-06-30' and term['session']=='2022-06-29'
    assert term['parent_positions']==[dict(slot_id=8,ticker='SRRA',quantity=35,entry_date='2022-06-27')]
    assert term['pending_at_parent']==dict(pending_sessions=0,stale_at_event=0,unresolved=False,native_term_sha256=term['native_term_sha256'])
    assert scope['additional_rows']==[]
    assert (original.HERE/original.CATALOG).read_bytes()==old

@pytest.mark.parametrize('change',['authority','adoption','bool_flag','held_empty','quantity0','bool_quantity','bool_slot','pending1','bool_pending',
    'stale1','bool_stale','unresolved','bad_pending_hash','native_before','native_after','prior_same','extra_at_parent','extra_future',
    'duplicate_slot','bad_date','foreign_field','fake_cash'])
def test_malformed_or_misrepresented_held_pending_scope_refuses(change):
    v=actual();q=v['queries'][0];s=q['scope'];t=s['terms'][0];p=t['pending_at_parent']
    if change=='authority':v['financial_authority']=True
    elif change=='adoption':v['input_adopted']=True
    elif change=='bool_flag':v['financial_authority']=0
    elif change=='held_empty':t['parent_positions']=[]
    elif change=='quantity0':t['parent_positions'][0]['quantity']=0
    elif change=='bool_quantity':t['parent_positions'][0]['quantity']=True
    elif change=='bool_slot':t['parent_positions'][0]['slot_id']=True
    elif change=='pending1':p['pending_sessions']=1
    elif change=='bool_pending':p['pending_sessions']=False
    elif change=='stale1':p['stale_at_event']=1
    elif change=='bool_stale':p['stale_at_event']=False
    elif change=='unresolved':p['unresolved']=True
    elif change=='bad_pending_hash':p['native_term_sha256']='0'*64
    elif change=='native_before':t['native_session']='2022-06-29'
    elif change=='native_after':t['native_session']='2022-07-01'
    elif change=='prior_same':t['session']=t['native_session']
    elif change in ('extra_at_parent','extra_future'):
        s['additional_rows']=[dict(ticker='SRRA',security_id=t['security_id'],session=s['parent_cursor'] if change=='extra_at_parent' else '2022-07-01',source_observation_sha256='0'*64,parent_positions=t['parent_positions'])]
    elif change=='duplicate_slot':t['parent_positions'].append(deepcopy(t['parent_positions'][0]))
    elif change=='bad_date':t['session']='2022-06-31'
    elif change=='foreign_field':t['unheld_only']=True
    else:t['cash_per_share']=55.
    with pytest.raises(ValueError):data.Registry.model_validate(v)

def test_disabled_foreign_arm_and_historical_root_never_activate():
    old={'P05':{'original':True}}
    assert data.selected_scopes(old,['P05'],enabled=False,root_lookup=lambda arm:(_ for _ in ()).throw(AssertionError()))==old
    assert data.selected_scopes(old,['P03'],enabled=True,root_lookup=lambda arm:(_ for _ in ()).throw(AssertionError()))==old
    lookup=lambda arm:root_spec(arm,'402b9ce10942fca4dcaac829303c6426a83a6a894ecf35d9cf472c4d84a8bb8d')
    assert data.selected_scopes(old,['P05'],enabled=True,root_lookup=lookup)==old

@pytest.mark.parametrize('change',['outer','cursor','count','inputs','authority'])
def test_exact_current_parent_axis_authority_and_full_input_count_refuse(change):
    root=root_spec('P05')
    if change=='outer':root['outer_sha256']='0'*64
    elif change=='cursor':root['selected_session']='2022-07-01'
    elif change=='count':root['measured_closes']=1133
    elif change=='inputs':root['repairs'].pop()
    else:root['financial_authority']=True
    with pytest.raises(ValueError):data.selected_scopes({},['P05'],enabled=True,root_lookup=lambda arm:root)

def test_removing_current_root_guard_really_accepts_foreign_outer():
    root=root_spec('P05');root['outer_sha256']='0'*64
    with pytest.raises(ValueError):data.selected_scopes({},['P05'],enabled=True,root_lookup=lambda arm:root)
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='selected_scopes')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='EXACT_CURRENT_ROOT_FULL_INPUT_COUNT_AXIS_AND_AUTHORITY' for v in node.value.args):self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-pending-root-guard-DATA-only>','exec'),scope)
    assert scope['selected_scopes']({},['P05'],enabled=True,root_lookup=lambda arm:root)['P05']['parent_outer_sha256']!='0'*64

def removed_method(owner,method,label):
    cls=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name==owner)
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==method);fn.decorator_list=[]
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value==label for v in node.value.args):self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-pending-model-guard-DATA-only>','exec'),scope)
    return scope[method]

def test_removing_authority_guard_really_accepts_a_financial_authority_claim():
    from types import SimpleNamespace
    value=SimpleNamespace(financial_authority=True,input_adopted=False)
    with pytest.raises(ValueError):data.Registry.source_only(value)
    assert removed_method('Registry','source_only','SOURCE_ROLES_GRANT_NO_INPUT_OR_FINANCIAL_AUTHORITY')(value) is value

@pytest.mark.parametrize('label,change',[('ONLY_EXACT_NATIVE_AT_PARENT_WITH_ZERO_PENDING_AGE','cursor'),
    ('EXACT_NONEMPTY_HELD_POSITION_AND_NATIVE_DAY_ROW_SCOPE','bad_ticker')])
def test_removing_pending_clock_or_role_guard_really_accepts_wrong_scope(label,change):
    scope=data.registry().queries[0].scope.model_copy(deep=True)
    if change=='cursor':scope=scope.model_copy(update=dict(parent_cursor='2022-07-01'))
    else:
        term=scope.terms[0];position=term.parent_positions[0].model_copy(update=dict(ticker='WRONG'))
        scope=scope.model_copy(update=dict(terms=[term.model_copy(update=dict(parent_positions=[position]))]))
    with pytest.raises(ValueError):data.Scope.exact_consumed_native_and_actual_held_role(scope)
    assert removed_method('Scope','exact_consumed_native_and_actual_held_role',label)(scope) is scope

def test_source_capture_format_guard_body_is_original_and_supports_pending_payload_schema2():
    import system_campaign_financial_future as future
    scope=data.selected_scopes({},['P05'],enabled=True,root_lookup=root_spec)['P05']
    assert future.source_schema(scope)=='research.own-parent-frozen-source-witnesses/2'
    assert scope['terms'][0]['pending_at_parent']['pending_sessions']==0

def test_original_source_payload_and_reconstruction_accept_native_only_pending_metadata_DTO():
    import system_campaign_financial_future as future
    scope=data.selected_scopes({},['P05'],enabled=True,root_lookup=root_spec)['P05'];term,=scope['terms']
    # Actual immutable native action; deliberately synthetic source-row DTO.
    original=dict(native_term={'cash_in_lieu_price_per_delivered_share': None, 'cash_per_share': None, 'delivered_issuer_id': None, 'delivered_security_id': None, 'delivered_ticker': None, 'entitlement_aggregation': 'HOLDER', 'exchange_ratio': None, 'kind': 'CASH_MERGER', 'reference': 'actions/acquisitionby deal_value_musd=1342.8', 'security_id': '324793693976033682', 'session': '2022-06-30'},source_row=dict(session='2022-06-29',security_id=term['security_id'],ticker='SRRA',issuer_id='SYNTHETIC',listing_first_session='2020-01-01',security_type_eligible='1'))
    assert future.digest(original['native_term'])==term['native_term_sha256']
    p,=term['parent_positions'];episode=dict(slot_id=p['slot_id'],ticker=p['ticker'],security_id=term['security_id'],current_shares=p['quantity'],entry_date=p['entry_date'])
    # This is source-query-shaped metadata, without run checkpoint/state hashes,
    # journals, prices or financial state. It never enters a canonical runtime.
    spec=root_spec('P05');dto=dict(not_canonical_checkpoint=True,sha256=scope['parent_outer_sha256'],
        source_cursor=scope['parent_cursor'],base=spec['base'],run=dict(state=dict(wealth_core=dict(episodes={'8':episode},
        terminal_pending_terms={term['security_id']:dict(terms=original['native_term'],stale_at_event=0)},
        terminal_pending_sessions={term['security_id']:0},unresolved_terminals={}))))
    payload=future.witness_payload(dto,'P05',scope,[original['native_term']],[original['source_row']],[])
    assert payload['additional_rows']==[] and payload['terms'][0]['pending_context']==term['pending_at_parent']
    assert future.validate_witness_capture(payload,spec,scope)==payload

def test_original_additional_row_parent_date_guard_still_refuses_same_day_quote():
    import system_campaign_financial_future as future
    scope=data.selected_scopes({},['P05'],enabled=True,root_lookup=root_spec)['P05'];term,=scope['terms']
    row=dict(session=scope['parent_cursor'],security_id=term['security_id'],ticker='SRRA',issuer_id='SYNTHETIC',
        security_type_eligible='1',listing_first_session='2020-01-01')
    scope['additional_rows']=[dict(session=row['session'],security_id=term['security_id'],ticker='SRRA',
        source_observation_sha256=future.digest(row),parent_positions=term['parent_positions'])]
    with pytest.raises(ValueError,match='UNMODIFIED_ADDITIONAL_ROW_AND_PARENT_ROLE'):
        future.additional_source_rows(scope,[row],[term['parent_positions']])

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):Fence().find_spec(name)
