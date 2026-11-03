"""Data-only exact incident regression; canonical gates execute only hosted."""
from copy import deepcopy
import ast,inspect,json
from pathlib import Path
import pytest
import system_campaign_future_amendment as m
from system_campaign_cash_batch import CashBatch

CAT=Path(__file__).parents[1]/'system-campaign-future-input-amendment-catalog.json'


def fixture():
    cp=dict(sha256=m.OUTER,source_cursor=m.CUTOVER,run=dict(checkpoint_sha256=m.INNER,input_sha256=m.INPUT),base={})
    suppress=dict(session='2021-04-30',security_id=m.SID)
    correct=dict(session='2021-05-03',security_id=m.SID,exchange_ratio=.8381,cash_in_lieu_price_per_delivered_share=0.,cash_per_share=None,reference='prior')
    bad={**correct,'reference':'wrong','cash_in_lieu_price_per_delivered_share':1.}
    # Semantic fixtures use local expected digests, never import financial code.
    docs={m.CORRECT:dict(schema='terminal-repair/1',suppress=[suppress],add=[correct]),
          m.TARGET:dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='a'*64,source_evidence=[],suppress=[suppress],add=[bad])}
    for i in range(5):
        day='2021-02-26' if i==0 else '2022-0'+str(i)+'-01'
        for field in ('suppress','add'):docs[m.TARGET][field].append(dict(session=day,security_id='other'+str(i),cash_per_share=float(i)))
    return cp,docs


def bind(monkeypatch,docs):
    monkeypatch.setattr(m,'TARGET_CONTENT',m.digest(docs[m.TARGET]))
    monkeypatch.setattr(m,'CORRECT_CONTENT',m.digest(docs[m.CORRECT]))
    monkeypatch.setattr(m,'RETIRED_SUPPRESS',m.digest(docs[m.TARGET]['suppress'][0]))
    monkeypatch.setattr(m,'RETIRED_ADD',m.digest(docs[m.TARGET]['add'][0]))
    monkeypatch.setattr(m,'PRESERVED_ADD',m.digest(docs[m.CORRECT]['add'][0]))


def test_future_view_preserves_archives_and_historical_term(monkeypatch):
    cp,docs=fixture();bind(monkeypatch,docs);before=deepcopy(docs)
    policy,view=m.projection(cp,docs,{m.CATALOG:'c'*64,m.COMPILER:'d'*64})
    assert len(view['add'])==len(view['suppress'])==4
    effective=m.effective_documents(docs,policy)
    assert docs==before and effective[m.CORRECT]==docs[m.CORRECT]
    assert len(effective[m.TARGET]['add'])==5
    assert effective[m.TARGET]['add'][0]['session']=='2021-02-26'


@pytest.mark.parametrize('kind',('predecessor','consumed','target','correct','second_conflict'))
def test_wrong_boundary_or_term_and_extra_conflict_refuse(monkeypatch,kind):
    cp,docs=fixture();bind(monkeypatch,docs)
    if kind=='predecessor':cp['run']['checkpoint_sha256']='0'*64
    elif kind=='consumed':cp['source_cursor']='2021-04-30'
    elif kind=='target':docs[m.TARGET]['add'][0]['exchange_ratio']=1.
    elif kind=='correct':docs[m.CORRECT]['add'][0]['cash_in_lieu_price_per_delivered_share']=1.
    else:docs['third']=dict(schema='terminal-repair/1',add=[dict(session='2022-01-01',security_id='other1',cash_per_share=999.)])
    with pytest.raises(ValueError):m.validate_conflict(cp,docs)


def test_actual_predecessor_guard_removal_is_detectable(monkeypatch):
    cp,docs=fixture();bind(monkeypatch,docs);cp['source_cursor']='2021-04-30'
    with pytest.raises(ValueError,match='EXACT_OWN_UNCONSUMED'):m.validate_conflict(cp,docs)
    tree=ast.parse(inspect.getsource(m.validate_conflict));node=tree.body[0]
    node.body=[v for v in node.body if not (isinstance(v,ast.Expr) and isinstance(v.value,ast.Call)
              and isinstance(v.value.func,ast.Name) and v.value.func.id=='need'
              and any(isinstance(x,ast.Constant) and x.value=='AMENDMENT_EXACT_OWN_UNCONSUMED_PREDECESSOR' for x in v.value.args))]
    scope=dict(m.__dict__);exec(compile(ast.fix_missing_locations(tree),'<own-boundary-guard-removed>','exec'),scope)
    scope['validate_conflict'](cp,docs)


def test_cash_registry_uses_one_qualified_cash_only_loader():
    c=json.loads(CAT.read_bytes());CashBatch(c)
    assert [v['ticker'] for v in c['terms']]==['FPRX','GNMK','GLUU','WIFI','PFPT','STMP','NUAN','CERN']
    assert [v['added']['cash_per_share'] for v in c['terms']]==[38.,24.05,12.5,14.,176.,330.,56.,95.]


@pytest.mark.parametrize('key,value',(('kind','CONVERSION'),('cash_per_share',-1.),('exchange_ratio',1.),('delivered_ticker','FAKE')))
def test_cash_only_loader_rejects_stock_or_invalid_cash(key,value):
    c=json.loads(CAT.read_bytes());c['terms'][0]['added'][key]=value
    with pytest.raises(ValueError):CashBatch(c)
