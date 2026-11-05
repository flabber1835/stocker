"""Original record/source membership falsifiers only; canonical finance fenced."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

CAP=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(CAP));sys.path.insert(0,str(Path(__file__).parent))


class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('ORIGINAL_LITERAL_DATA_ONLY:'+fullname)


sys.meta_path.insert(0,Fence())
import system_campaign_qualified_own_cash_literals as data


def catalog():
    return json.loads((Path(data.__file__).parent/'system-campaign-p07-own1196-gbt-original-cash-literal.json').read_bytes())


def two():
    value=catalog();name='system-campaign-spring2023-cash-calendar-terminal-facts.json';raw=(CAP/name).read_bytes()
    prior,=[t for t in json.loads(raw)['terms'] if t['ticker']=='CEMI']
    index,=[i for i,t in enumerate(value['source_data']['payload']['terms'])if t['source_row']['ticker']=='CEMI']
    actual=value['source_data']['payload']['terms'][index]
    term=deepcopy(prior)
    term.update(**{k:deepcopy(value['terms'][0][k]) for k in data.FRESH})
    term.update(native=actual['native_term'],identity_witness=actual['identity_witness'],parent_positions=actual['parent_positions'],
        retained_qualified_legal_term=dict(catalog_file=name,catalog_sha256=data.original.sha(raw),term_sha256=data.original.digest(prior)))
    value['terms'].append(term);value['selected_source_indices'].append(index)
    return value


def test_actual_gbt_literal_preserves_primary_extraction_without_invented_usd_schema(tmp_path):
    value=catalog();assert data.validate(value)
    term,=value['terms']
    assert term['arm']=='P07' and term['parent_positions']==[]
    assert term['primary_extraction']['cash_per_ordinary_common_share']=='68.50'
    assert 'cash_currency' not in term['primary_extraction']
    path=tmp_path/'literal.json';raw=data.original.encoded(value);path.write_bytes(raw)
    obj=data.QualifiedOriginalCashLiterals(path)
    assert obj.catalog==value and obj.catalog_sha==data.original.sha(raw) and obj.compiler_sha==value['loader_sha256']


def test_original_next_session_record_keeps_exact_rule_and_date():
    value=two();assert data.validate(value)
    assert value['terms'][1]['recognition_rule']=='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY'
    assert value['terms'][1]['preopen_completion_confirmed'] is False


def trq():
    return json.loads((Path(data.__file__).parent/'system-campaign-p07-own1196-trq-original-cash-literal.json').read_bytes())


def test_trq_preserves_original_inactive_primary_and_exact_research_fx_model():
    value=trq();assert data.validate(value);term,=value['terms']
    assert term['parent_positions']==[] and term['arm']=='P07'
    assert term['primary_extraction']['source_context']['parent_held_quantity']==82
    assert term['primary_extraction']['active'] is False
    assert term['added']['cash_per_share'].hex()=='0x1.f936b43dcf596p+4'
    assert term['research_assumption']['raw_cash_currency']=='CAD'
    assert term['research_assumption']['actual_usd_payment_claimed'] is False
    assert term['research_assumption']['actual_settlement_claimed'] is False


@pytest.mark.parametrize('change',['raw_currency','rate','precision','normalized','cash43','claim','borrowed_quantity','primary'])
def test_trq_normalization_or_actual_role_mutation_refuses(change):
    value=trq();term=value['terms'][0];model=term['research_assumption']
    if change=='raw_currency':model['raw_cash_currency']='USD'
    elif change=='rate':model['exchange_rate']='1.4'
    elif change=='precision':model['decimal_precision']=49
    elif change=='normalized':model['normalized_usd_decimal']='31.5'
    elif change=='cash43':term['added']['cash_per_share']=43.
    elif change=='claim':model['actual_usd_payment_claimed']=True
    elif change=='borrowed_quantity':term['parent_positions']=[dict(slot_id=0,ticker='TRQ',quantity=82,entry_date='2022-11-07')]
    else:term['primary_extraction']['active']=True
    with pytest.raises(ValueError):data.validate(value)


@pytest.mark.parametrize('change',[None,'not_registered','changed_prefix','bool_count'])
def test_registered_catalog_append_preserves_exact_earlier_input_generation(tmp_path,monkeypatch,change):
    import system_campaign_financial_future as future
    term=deepcopy(catalog()['terms'][0]);name=future.OWN_CASH_CATALOG
    raw=(CAP/name).read_bytes();value=json.loads(raw);old_pin=data.original.sha(raw);count=len(value['terms'])
    value['terms'].append(dict(synthetic_input_metadata_only=True))
    if change=='changed_prefix':value['terms'][0]['description']+=' changed'
    raw=data.original.encoded(value);(tmp_path/name).write_bytes(raw)
    monkeypatch.setattr(data.original,'__file__',str(tmp_path/'synthetic-input-only.py'))
    monkeypatch.setattr(future,'OWN_CASH_SHA',data.original.sha(raw))
    closed=dict(future.CLOSED_CASH_GENERATIONS)
    if change!='not_registered':closed[old_pin]=False if change=='bool_count' else count
    monkeypatch.setattr(future,'CLOSED_CASH_GENERATIONS',closed)
    if change is None:data.validate_original_literal(term)
    else:
        with pytest.raises(ValueError):data.validate_original_literal(term)


def test_closed_generation_type_guard_removal_admits_boolean_prefix_count(tmp_path,monkeypatch):
    import system_campaign_financial_future as future
    term=deepcopy(catalog()['terms'][0]);name=future.OWN_CASH_CATALOG
    value=json.loads((CAP/name).read_bytes());prior,=[v for v in value['terms']if v['ticker']=='GBT']
    prefix=dict(value,terms=[prior]);pin=data.original.sha(data.original.encoded(prefix))
    current=dict(value,terms=[prior,dict(synthetic_input_metadata_only=True)])
    raw=data.original.encoded(current);(tmp_path/name).write_bytes(raw)
    term[data.REFERENCE]['catalog_sha256']=pin
    monkeypatch.setattr(data.original,'__file__',str(tmp_path/'synthetic-input-only.py'))
    monkeypatch.setattr(future,'OWN_CASH_SHA',data.original.sha(raw))
    monkeypatch.setattr(future,'CLOSED_CASH_GENERATIONS',{pin:True})
    with pytest.raises(ValueError,match='ONLY_REGISTERED_CLOSED_GENERATION'):data.validate_original_literal(term)
    removed('validate_original_literal','ORIGINAL_CASH_LITERALS_ONLY_REGISTERED_CLOSED_GENERATION')(term)


@pytest.mark.parametrize('change',['bool_index','duplicate_index','wrong_index','outside','root','native','role',
    'source_authority','amount','primary_extraction','recognition','original_record','original_catalog','unsafe_path','extra_field','no_reference'])
def test_foreign_or_changed_original_input_refuses(change):
    value=catalog();term=value['terms'][0]
    if change=='bool_index':value['selected_source_indices'][0]=False
    elif change=='duplicate_index':value['selected_source_indices']*=2
    elif change=='wrong_index':value['selected_source_indices'][0]=1
    elif change=='outside':value['selected_source_indices'][0]=1000
    elif change=='root':value['parent_root_admission_sha256']='0'*64
    elif change=='native':term['native_term_sha256']='0'*64
    elif change=='role':term['parent_positions']=[dict(slot_id=0,ticker='GBT',quantity=1,entry_date='2022-01-01')]
    elif change=='source_authority':value['source_data']['qualification']['financial_authority']=True
    elif change=='amount':term['added']['cash_per_share']=69.
    elif change=='primary_extraction':term['primary_extraction']['cash_per_ordinary_common_share']='69.00'
    elif change=='recognition':term['recognition_rule']='SOURCE_ONLY_UNQUALIFIED'
    elif change=='original_record':term[data.REFERENCE]['term_sha256']='0'*64
    elif change=='original_catalog':term[data.REFERENCE]['catalog_sha256']='0'*64
    elif change=='unsafe_path':term[data.REFERENCE]['catalog_file']='../outside.json'
    elif change=='extra_field':term['unqualified_extra_fact']=True
    else:term.pop(data.REFERENCE)
    with pytest.raises((ValueError,KeyError)):data.validate(value)


def removed(function,label):
    fn,=[n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name==function]
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call)and any(isinstance(v,ast.Constant)and v.value==label for v in node.value.args):return None
            return self.generic_visit(node)
    fn=Remove().visit(fn);scope=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-original-literal-guard>','exec'),scope)
    return scope[function]


def test_amount_guard_removal_really_admits_foreign_cash_amount(monkeypatch):
    value=catalog();value['terms'][0]['added']['cash_per_share']=69.
    with pytest.raises(ValueError,match='ALL_ORIGINAL_FIELDS'):data.validate(value)
    monkeypatch.setattr(data,'validate_original_literal',removed('validate_original_literal','ORIGINAL_CASH_LITERALS_ALL_ORIGINAL_FIELDS_AND_HELD_AUTHORITY'))
    assert data.validate(value)


def test_member_order_guard_removal_really_admits_reordered_source_members(monkeypatch):
    value=two();value['terms'].reverse();value['selected_source_indices'].reverse()
    with pytest.raises(ValueError,match='SORTED_UNIQUE'):data.validate(value)
    monkeypatch.setattr(data,'selected_members',removed('selected_members','ORIGINAL_CASH_LITERALS_SORTED_UNIQUE_EXACT_SOURCE_MEMBERS'))
    assert data.validate(value)


def test_registered_original_catalog_guard_removal_admits_unregistered_record_copy(tmp_path,monkeypatch):
    term=deepcopy(catalog()['terms'][0]);original_raw=(CAP/term[data.REFERENCE]['catalog_file']).read_bytes()
    prior,=[t for t in json.loads(original_raw)['terms']if t['ticker']=='GBT']
    raw=data.original.encoded(dict(terms=[prior]));name='unregistered-copy.json';(tmp_path/name).write_bytes(raw)
    (tmp_path/'system-campaign-parallel-discovery-request-001.json').write_bytes((CAP/'system-campaign-parallel-discovery-request-001.json').read_bytes())
    term[data.REFERENCE].update(catalog_file=name,catalog_sha256=data.original.sha(raw))
    monkeypatch.setattr(data.original,'__file__',str(tmp_path/'synthetic-metadata-only.py'))
    with pytest.raises(ValueError,match='REGISTERED_FROZEN_ORIGINAL_CATALOG'):data.validate_original_literal(term)
    without=removed('validate_original_literal','ORIGINAL_CASH_LITERALS_REGISTERED_FROZEN_ORIGINAL_CATALOG')
    without(term)


def test_undo_all_source_subset_policy_and_extraction_changes_restores_whole_original_AST():
    fn=data.validator_tree();old,=[n for n in ast.parse(Path(data.original.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='validate']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Assign)and ast.unparse(n.targets[0])=='(captured, declared, checked_members)')]
    class Undo(ast.NodeTransformer):
        def visit_Name(self,node):
            if node.id=='checked_members':return ast.copy_location(ast.parse("review['terms']",mode='eval').body,node)
            return node
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if any(isinstance(v,ast.Constant)and v.value=='CASH_BATCH_ONLY_EXISTING_CASH_POLICIES'for v in node.args):
                node.args[0]=ast.parse("term['recognition_rule'] == PREOPEN",mode='eval').body
            return node
    fn=Undo().visit(fn);loop,=[n for n in fn.body if isinstance(n,ast.For)];old_loop,=[n for n in old.body if isinstance(n,ast.For)]
    site,=[i for i,n in enumerate(loop.body)if isinstance(n,ast.Expr)and ast.unparse(n)=='validate_original_literal(term)']
    original_site,=[i for i,n in enumerate(old_loop.body)if isinstance(n,ast.Assign)and ast.unparse(n.targets[0])=='extraction']
    loop.body[site:site+1]=deepcopy(old_loop.body[original_site:original_site+2])
    assert ast.dump(fn,include_attributes=False)==ast.dump(old,include_attributes=False)


@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
