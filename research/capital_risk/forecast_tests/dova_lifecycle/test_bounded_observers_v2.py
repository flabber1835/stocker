"""Synthetic ledger/observation metadata and explicit common-share arithmetic."""
import sys,json
from copy import deepcopy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_bounded_runtime_v2 import Fence
sys.meta_path.insert(0,Fence())
import system_campaign_bounded_sensor_observers_v2 as data

def term(kind='CONVERSION'):
    return dict(ticker='SYNTHETIC_OLD',security_id='SYNTHETIC_SOURCE',added=dict(kind=kind,session='2099-01-03',security_id='SYNTHETIC_SOURCE',
        exchange_ratio='0.5',cash_per_share=2. if kind=='CASH_PLUS_STOCK' else None,cash_in_lieu_price_per_delivered_share=10.,
        delivered_security_id='SYNTHETIC_TARGET',delivered_ticker='SYNTHETIC_NEW',delivered_issuer_id='SYNTHETIC_ISSUER',reference='SYNTHETIC_COMMON_SHARE_CONTRACT'))

def source_lot(slot,shares):
    return dict(slot_id=slot,security_id='SYNTHETIC_SOURCE',ticker='SYNTHETIC_OLD',initial_shares=shares,current_shares=shares,
        signal_date='2098-01-01',entry_date='2098-01-02',market_sessions_held=31,review_completed=True,
        exit_pending=False,exit_reason=None,source_lots=[{'SYNTHETIC_ORIGINAL_SOURCE':True}])

def delivered_lot(source,shares,cash,cil,kind='CASH_PLUS_STOCK'):
    result=deepcopy(source)
    result.update(security_id='SYNTHETIC_TARGET',ticker='SYNTHETIC_NEW',issuer_id='SYNTHETIC_ISSUER',
        current_shares=shares,initial_shares=max(1,int(round(source['initial_shares']*0.5))))
    result['source_lots'].append(dict(kind=kind,session='2099-01-03',from_security_id='SYNTHETIC_SOURCE',from_ticker='SYNTHETIC_OLD',
        shares_in=source['current_shares'],exchange_ratio=0.5,exchange_ratio_exact='0.5',entitlement_aggregation='HOLDER',
        shares_delivered=shares,cash_consideration=cash,cash_in_lieu=cil,to_security_id='SYNTHETIC_TARGET',to_ticker='SYNTHETIC_NEW',
        reference='SYNTHETIC_COMMON_SHARE_CONTRACT'))
    return result

def case(kind='CONVERSION',held=True):
    t=term(kind);a=t['added'];source=source_lot(1,5)
    before=dict(wealth_core=dict(episodes={'1':source} if held else {}))
    opened=dict(wealth_core=dict(episodes={'1':delivered_lot(source,2.,10. if kind=='CASH_PLUS_STOCK' else 0.,5.,kind)} if held else {},
        terminal_pending_terms={},terminal_pending_sessions={}),pending=[])
    cash=15. if kind=='CASH_PLUS_STOCK' else 5.
    event=dict(security_id=t['security_id'],session=a['session'],event_type='CONVERSION',reason=kind,price=a['cash_per_share'],fees=0.,
        cash_before=100.,cash_after=100.+cash,cash_delta=cash,shares_delta=-3.,detail=dict(shares_in=5,shares_delivered=2.,
        delivered_security_id='SYNTHETIC_TARGET',delivered_ticker='SYNTHETIC_NEW',exchange_ratio_exact='0.5',
        exact_fractional_entitlement='1/2',cash_consideration=10. if kind=='CASH_PLUS_STOCK' else 0.,cash_in_lieu=5.,
        reference=a['reference'],entitlement_aggregation='HOLDER'))
    stock=[]
    if kind=='CASH_PLUS_STOCK':
        stock=[dict(security_id=t['security_id'],session=a['session'],actual_context_call=True,applied=held)]
        if not held:stock[0].update(unheld_noop=True,postcondition=dict(actual_held=False,quantity=0,nominal_cash=0.),
            before_state_sha256='same',after_state_sha256='same',before_ledger_sha256='same',after_ledger_sha256='same')
    record=dict(session='2099-01-03',passed=True,financial_source_changed=False,source=[],cash=[],risk=[],engine_calls=0,order=[],stock=stock)
    return t,before,opened,[event] if held else [],record

@pytest.mark.parametrize('kind',['CONVERSION','CASH_PLUS_STOCK'])
@pytest.mark.parametrize('held',[True,False])
def test_independent_holder_delivery_cash_and_unheld_noop(kind,held):
    result=data.stock_event(*case(kind,held))
    assert result['source_lots']==int(held) and result['delivered_whole']==(2 if held else 0)
    assert result['cash_in_lieu']==('5' if held else '0')

@pytest.mark.parametrize('change',['target','shares','cash','reference','fraction','fee','source_left','pending_left','double_cash','mixed_call',
    'destination','age','provenance','session'])
def test_wrong_delivery_cash_source_or_duplicate_consideration_refuses(change):
    t,before,opened,events,record=case('CASH_PLUS_STOCK');event=events[0]
    if change=='target':event['detail']['delivered_security_id']='FOREIGN'
    elif change=='shares':event['detail']['shares_delivered']=3.
    elif change=='cash':event['cash_delta']=16.
    elif change=='reference':event['detail']['reference']='FOREIGN'
    elif change=='fraction':event['detail']['exact_fractional_entitlement']='0'
    elif change=='fee':event['fees']=1.
    elif change=='source_left':opened['wealth_core']['episodes']=deepcopy(before['wealth_core']['episodes'])
    elif change=='pending_left':opened['pending']=[dict(security_id=t['security_id'])]
    elif change=='double_cash':events.append(dict(security_id=t['security_id'],session=t['added']['session'],event_type='CASH_MERGER'))
    elif change=='mixed_call':record['stock'][0]['actual_context_call']=False
    elif change=='destination':opened['wealth_core']['episodes']['1']['current_shares']=3.
    elif change=='age':opened['wealth_core']['episodes']['1']['market_sessions_held']=0
    elif change=='provenance':opened['wealth_core']['episodes']['1']['source_lots'][0]={'FOREIGN':True}
    else:record['session']='2099-01-04'
    with pytest.raises(ValueError):data.stock_event(t,before,opened,events,record)

@pytest.mark.parametrize('rule',['SYNTHETIC_SOURCE_ONLY','RESEARCH_NATIVE_UNHELD_CASH_SOURCE_CLOSE','RESEARCH_SOURCE_EXIT'])
def test_source_only_rules_cannot_be_reclassified_as_ordinary(rule):
    t=term();t['recognition_rule']=rule
    with pytest.raises(ValueError,match='NO_SOURCE_ONLY_UPGRADE'):data.merge([t])

def test_same_key_conflicting_whole_term_refuses_and_clones_are_independent():
    t=term();wrong=deepcopy(t);wrong['ticker']='FOREIGN'
    with pytest.raises(ValueError):data.merge([t],[wrong])
    result=data.merge([t],[deepcopy(t)]);assert len(result)==1
    result[0]['ticker']='CHANGED';assert t['ticker']=='SYNTHETIC_OLD'

def test_decimal_float_ratio_uses_its_contract_spelling():
    values=case('CASH_PLUS_STOCK');values[0]['added']['exchange_ratio']=0.5
    assert data.stock_event(*values)['delivered_whole']==2

def test_multiple_source_lots_preserve_holder_floor_and_original_binary64_cash_order():
    t,before,opened,events,record=case('CASH_PLUS_STOCK')
    before['wealth_core']['episodes']={'8':source_lot(8,3),'1':source_lot(1,2)}
    opened['wealth_core']['episodes']={'1':delivered_lot(before['wealth_core']['episodes']['1'],0.8,4.,2.),
        '8':delivered_lot(before['wealth_core']['episodes']['8'],1.2,6.,3.)}
    first=deepcopy(events[0]);second=deepcopy(events[0])
    first.update(cash_before=100.,cash_after=106.,cash_delta=6.,shares_delta=0.8-2)
    first['detail'].update(shares_in=2,shares_delivered=0.8,exact_fractional_entitlement='1/5',cash_consideration=4.,cash_in_lieu=2.)
    second.update(cash_before=106.,cash_after=115.,cash_delta=9.,shares_delta=1.2-3)
    second['detail'].update(shares_in=3,shares_delivered=1.2,exact_fractional_entitlement='3/10',cash_consideration=6.,cash_in_lieu=3.)
    result=data.stock_event(t,before,opened,[first,second],record)
    assert result['source_lots']==2 and result['delivered_whole']==2
    second['detail']['shares_delivered']=1.2000001
    with pytest.raises(ValueError):data.stock_event(t,before,opened,[first,second],record)


def test_explicit_original_hundredth_rounding_settles_only_cash_fraction():
    t,before,opened,events,record=case('CASH_PLUS_STOCK');a=t['added'];event=events[0]
    a.update(exchange_ratio='0.2666',terminal_terms_schema='terminal-cil-rounding/1',
        cash_in_lieu_fraction_rounding='NEAREST_HUNDREDTH_HALF_UP')
    event.update(cash_after=113.3,cash_delta=113.3-100.,shares_delta=-4.)
    event['detail'].update(exchange_ratio_exact='0.2666',shares_delivered=1.,exact_fractional_entitlement='333/1000',cash_in_lieu=3.3)
    successor=opened['wealth_core']['episodes']['1'];successor.update(current_shares=1.,initial_shares=1)
    successor['source_lots'][-1].update(exchange_ratio=0.2666,exchange_ratio_exact='0.2666',shares_delivered=1.,cash_in_lieu=3.3)
    assert data.stock_event(t,before,opened,events,record)['cash_in_lieu']=='33/10'
    event['detail']['cash_in_lieu']=3.33
    with pytest.raises(ValueError):data.stock_event(t,before,opened,events,record)

def test_same_day_cash_and_mixed_call_sets_are_checked_before_projection():
    mixed=term('CASH_PLUS_STOCK');cash=deepcopy(mixed);cash['security_id']=cash['added']['security_id']='SYNTHETIC_CASH';cash['added']['kind']='CASH_MERGER'
    record=case('CASH_PLUS_STOCK')[4];record['cash']=[dict(security_id='SYNTHETIC_CASH')];record['order']=['CASH:SYNTHETIC_CASH']
    cash_records,other=data.grouped_records([cash,mixed],{'2099-01-03':record},'2099-01-03')
    assert cash_records['2099-01-03']['stock']==[]
    assert len(other)==1 and other[0][1]['cash']==[] and other[0][1]['order']==[] and len(other[0][1]['stock'])==1
    wrong=deepcopy(record);wrong['stock'].append(dict(security_id='FOREIGN'))
    with pytest.raises(ValueError,match='WHOLE_DAILY_CALL_SET'):data.grouped_records([cash,mixed],{'2099-01-03':wrong},'2099-01-03')

def test_removing_stock_amount_guard_accepts_wrong_cash_and_is_detected():
    import ast
    t,before,opened,events,record=case('CASH_PLUS_STOCK');events[0]['cash_delta']+=1.
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='stock_event')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='BOUNDED_ORDINARY_EXACT_HOLDER_DELIVERY_AND_ORIGINAL_CASH_OPERATION_ORDER' for v in node.value.args):
                self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-stock-cash-guard-synthetic-metadata-only>','exec'),scope)
    with pytest.raises(ValueError):data.stock_event(t,before,opened,events,record)
    assert scope['stock_event'](t,before,opened,events,record)['delivered_whole']==2


def test_removing_continuation_guard_accepts_wrong_delivered_position_and_is_detected():
    import ast
    values=case('CASH_PLUS_STOCK');values[2]['wealth_core']['episodes']['1']['current_shares']=3.
    fn=next(n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='stock_event')
    class Remove(ast.NodeTransformer):
        hits=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant)
                and v.value=='BOUNDED_ORDINARY_EXACT_POSITION_CONTINUATION_AND_SOURCE_PROVENANCE' for v in node.value.args):
                self.hits+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=ast.fix_missing_locations(remove.visit(fn));assert remove.hits==1
    scope=dict(vars(data));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<removed-continuation-guard-synthetic-metadata-only>','exec'),scope)
    with pytest.raises(ValueError,match='POSITION_CONTINUATION'):data.stock_event(*values)
    assert scope['stock_event'](*values)['delivered_whole']==2


def tail_case(root,change=None):
    material=dict(arm='P03',parent_outer_sha256='1'*64,financial_source_changed=False,provider_metadata_upgraded=False,terms=[term()])
    if change=='source_upgrade':material['terms'][0]['recognition_rule']='SYNTHETIC_SOURCE_ONLY'
    if change=='financial_source':material['financial_source_changed']=True
    raw=data.encoded(material);name='hydrated-future-financial-terminal-catalog-'+material['parent_outer_sha256']+'.json'
    (root/('FOREIGN.json' if change=='filename' else name)).write_bytes(raw)
    doc=dict(schema='terminal-repair/1',source_evidence=[dict(reference=data.REFERENCE,sha256=data.sha(raw))],
        add=[material['terms'][0]['added']])
    if change=='subset':doc['add']=[]
    if change=='pin':doc['source_evidence'][0]['sha256']='0'*64
    blob=data.encoded(doc);pin=data.sha(blob);repairs=root/'book/repairs';repairs.mkdir(parents=True)
    (repairs/(pin+'.json')).write_bytes(blob)
    return dict(NONCANONICAL_INPUT_DESCRIPTOR_DTO=True,repairs=[None]*16+[dict(filename=pin+'.json',sha256=pin)])


def test_later_material_is_bound_to_full_input_bytes_and_preserved_whole(tmp_path):
    cp=tail_case(tmp_path);terms,resources=data.tail_materials(tmp_path,cp)
    assert terms==[term()] and len(resources)==1
    raw=next(iter(resources.values()));assert json.loads(raw)['terms']==terms
    assert next(iter(resources)).startswith(data.DIRECTORY+'/materials/'+cp['repairs'][16]['sha256']+'/')


@pytest.mark.parametrize('change',['source_upgrade','financial_source','filename','subset','pin'])
def test_later_material_refuses_unbound_or_reclassified_terms(tmp_path,change):
    cp=tail_case(tmp_path,change)
    with pytest.raises(ValueError):data.tail_materials(tmp_path,cp)
