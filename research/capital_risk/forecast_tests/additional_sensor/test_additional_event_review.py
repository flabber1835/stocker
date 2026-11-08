"""Original declared-event review block on synthetic pre-event metadata only."""
import copy,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_additional_sensor import data,runtime,env,fixture,fence,DEP

@pytest.fixture
def event(env,monkeypatch,tmp_path):
    import system_campaign_zogenix_review as z
    from system_campaign_zogenix_facts import PRIVATE
    from system_campaign_zogenix_input import SID,NATIVE,DAY
    p=env.p;contract=json.loads((DEP/'system-campaign-zogenix-sensor-contract.json').read_bytes())
    provider=json.loads((Path(__file__).parent/'fixtures/original-provider-selected-rows.json').read_bytes())
    rows=[v for v in provider['rows'] if v['date']==NATIVE and 'ZGNX' in (v['ticker'],v['contraticker'])]
    source=dict(schema='research.zogenix-sensor-private-event/1',contract=contract,actual_native=p['event']['native_term'],
        source_witnesses=env.fixture['original_zogenix_rows'],provider_rows=rows,session=DAY,security_id=SID,
        source_quote_present=False,split_ratio='1',source_metadata_unchanged=True,right_market_price_observed=False)
    (env.root/PRIVATE).write_bytes(data.encoded(source))
    # Synthetic anchor DTO: never restored, recheckpointed or adopted.
    state=dict(wealth_core=dict(episodes={}),pending=[],median5=dict(selected=[SID,'OTHER'],selected_closes={SID:100.,'OTHER':100.}),
        feed=dict(series={SID:dict(signal_basis_anchor=[NATIVE,100.,100.])}))
    cp=dict(synthetic_pre_event_metadata=True,source_cursor=NATIVE,run=dict(state=state))
    row=dict(session=DAY,prior_state_sha256='1'*64,input_sha256='2'*64,
        material=dict(rows=[dict(security_id=SID,prior=100.,current=[26.,28.]),dict(security_id='OTHER',prior=100.,current=[101.,101.])]),
        additional_event_basis=dict(selected=True,session=DAY,security_id=SID,prior_session=NATIVE,raw_anchor='100.0',signal_anchor='100.0',split='1',
            source_term_sha256=data.digest({**source['actual_native'],'session':DAY}),source_event_sha256=data.digest(source),
            signal_consideration_interval=[26.,28.]))
    monkeypatch.setattr(runtime,'hosted',lambda:None)
    monkeypatch.setattr(z,'event_checkpoint',lambda root,row:(cp,dict(synthetic_actual_archive_resolution=True)))
    return SimpleNamespace(root=env.root,state=state,cp=cp,row=row,source=source,PRIVATE=PRIVATE,SID=SID,DAY=DAY,NATIVE=NATIVE)

def test_full_original_event_range_is_prevalidated_before_suffix_permission(event):
    allowed,resolution=runtime.event_rows(event.root,[event.row])
    assert allowed=={data.digest(event.row):(event.DAY,event.SID,[26.,28.])}
    assert len(resolution)==1

@pytest.mark.parametrize('bad',['range','selected','anchor','source','split','owned','pending','otherday','missing'])
def test_original_event_review_falsifiers(event,bad):
    row=copy.deepcopy(event.row)
    if bad=='range':row['material']['rows'][0]['current']=[28.,28.]
    elif bad=='selected':row['additional_event_basis']['selected']=False
    elif bad=='anchor':event.state['feed']['series'][event.SID]['signal_basis_anchor'][0]='2022-03-03'
    elif bad=='source':row['additional_event_basis']['source_event_sha256']='0'*64
    elif bad=='split':row['additional_event_basis']['split']='2'
    elif bad=='owned':event.state['wealth_core']['episodes']['x']=dict(security_id=event.SID)
    elif bad=='pending':event.state['pending']=[dict(security_id=event.SID)]
    elif bad=='otherday':row['session']='2022-03-08'
    else:row.pop('additional_event_basis')
    with pytest.raises((ValueError,KeyError)):runtime.event_rows(event.root,[row])

def test_actual_unselected_event_supplies_no_additional_interval_permission(event):
    event.state['median5']['selected']=['OTHER']
    event.row['material']['rows']=event.row['material']['rows'][1:]
    event.row['additional_event_basis']=dict(session=event.DAY,security_id=event.SID,selected=False)
    allowed,resolution=runtime.event_rows(event.root,[event.row])
    assert allowed=={} and len(resolution)==1


def test_original_plus_new_single_guard_refuses_foreign_interval(event):
    import ast
    from system_campaign_uncertainty_math import Interval
    tree=data.suffix_tree()
    guard,=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='need'
        and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='BRANCH_ONLY_DECLARED_EVENT_MAY_VARY']
    allowed,_=runtime.event_rows(event.root,[event.row])
    def addition(row,item):
        expected=allowed.get(data.digest(row))
        return expected is not None and (row['session'],item['security_id'],item['current'])==expected
    program=compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(guard)],type_ignores=[])),'<exact-original-plus-one-declared-event-guard>','exec')
    scope=dict(need=data.need,row=event.row,item=event.row['material']['rows'][0],bound=Interval(26.,28.),
        DAY='2019-10-22',SID='941065113449292610',additional_event_allows=addition)
    exec(program,scope)
    bad=copy.deepcopy(event.row);bad['material']['rows'][0]['security_id']='UNDECLARED'
    scope.update(row=bad,item=bad['material']['rows'][0])
    with pytest.raises(ValueError):exec(program,scope)
    # Remove only the varying-event guard: this same unregistered interval is admitted.
    guard.args[0]=ast.Constant(True)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(guard)],type_ignores=[])),'<meaningful-event-guard-removal>','exec'),scope)
