"""Pure source/cache guard checks; actual canonical integration is hosted."""
import ast,hashlib,json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_p01_discovery_anchors as anchors

LAYOUT=b'''class Buffer:
    def prepare(self,prior,version,formation=False):
        axis=list(self.axis)
        origin=self.index-299
        live=protected(prior)
        signals,histories,anchors=[],{},{}
        for sid in live:
            ring=self.rings.get(sid)
            anchor=prior.feed.get('series',{}).get(sid,{}).get('signal_basis_anchor')
            if ring is None or not anchor or anchor[0] not in axis:
                raise TemporalViolation('LIVE_ANCHOR_OUTSIDE_WINDOW: '+sid)
            anchors[sid]=ring.anchor(sid,anchor[0],axis,origin)
            histories[sid]=ring.canonical(sid,axis,origin,self.index-260,self.index)
        return signals,histories,anchors
'''

def test_source_bound_tree_changes_only_the_single_anchor_branch(monkeypatch):
    monkeypatch.setattr(anchors,'ADAPTER_SHA',hashlib.sha256(LAYOUT).hexdigest())
    tree=anchors.prepare_tree(LAYOUT)
    text=ast.unparse(tree)
    assert text.count('_remember_source_anchors(')==1 and text.count('_retained_source_anchor(')==1
    assert 'ring.anchor(sid, anchor[0], axis, origin)' in text
    assert 'ring.canonical(sid, axis, origin, self.index - 260, self.index)' in text
    with pytest.raises(ValueError,match='EXACT_FROZEN_INPUT_ADAPTER'):anchors.prepare_tree(LAYOUT+b'\n')

def test_actual_source_guard_removal_admits_changed_source(monkeypatch):
    monkeypatch.setattr(anchors,'ADAPTER_SHA',hashlib.sha256(LAYOUT).hexdigest())
    fn,=[n for n in ast.parse(Path(anchors.__file__).read_bytes()).body
          if isinstance(n,ast.FunctionDef) and n.name=='prepare_tree']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='DISCOVERY_ANCHOR_EXACT_FROZEN_INPUT_ADAPTER' for v in ast.walk(n)))]
    scope=dict(vars(anchors));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual-input-source-guard-removed>','exec'),scope)
    scope['prepare_tree'](LAYOUT+b'\n')

def cache(tmp_path):
    value=anchors.RetainedAnchors(tmp_path,None,source_sha256='1'*64,input_sha256='3'*64)
    value.stream=(tmp_path/anchors.STREAM).open('xb')
    value.m=SimpleNamespace(VendorBar=lambda day,sid,ticker,raw,*a,signal_close:SimpleNamespace(
        session=day,security_id=sid,ticker=ticker,raw_close=raw,signal_close=signal_close))
    return value

def source_bar(day='2018-01-02',sid='SYNTHETIC',raw=12.5):
    return SimpleNamespace(session=day,security_id=sid,ticker='SYNTHETIC',raw_close=raw,signal_close=13.)

def prior():return SimpleNamespace(last_processed_session='2020-01-31',state_hash='2'*64)
def buffer():return SimpleNamespace(current=SimpleNamespace(day='2020-02-03',bars=()))

def test_exact_observed_anchor_can_outlive_window_without_current_quote(tmp_path):
    c=cache(tmp_path);c.targets={'SYNTHETIC':'2018-01-02'}
    bar=source_bar();c.observe(SimpleNamespace(day=bar.session,bars=(bar,)))
    state=prior();b=buffer();before=vars(state).copy()
    actual=c.retained(b,state,'SYNTHETIC',['2018-01-02',12.5,13.])
    assert actual.session=='2018-01-02' and actual.raw_close==12.5
    assert vars(state)==before and b.current.bars==()
    assert c.commitment()['rows']==1
    c.stream.close();row=json.loads((tmp_path/anchors.STREAM).read_bytes())
    assert row['record']['source_anchor']['origin']=='FROZEN_SOURCE_PACKET'
    assert row['record']['session']=='2020-02-03'

@pytest.mark.parametrize('change',[None,'missing','wrong_day','wrong_raw','future_use'])
def test_no_source_or_mismatched_basis_refuses(tmp_path,change):
    c=cache(tmp_path);a=['2018-01-02',12.5,13.];s=prior();b=buffer()
    if change!='missing':c.store(source_bar(),'FROZEN_SOURCE_PACKET')
    if change is None:a=None
    elif change=='wrong_day':a[0]='2018-01-03'
    elif change=='wrong_raw':a[1]=12.6
    elif change=='future_use':s.last_processed_session='2020-02-03'
    with pytest.raises(ValueError,match='DISCOVERY_'):c.retained(b,s,'SYNTHETIC',a)
    assert c.commitment()['rows']==0;c.stream.close()

def test_actual_basis_guard_removal_admits_changed_retained_raw(tmp_path):
    c=cache(tmp_path);c.store(source_bar(),'FROZEN_SOURCE_PACKET')
    owner,=[n for n in ast.parse(Path(anchors.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='RetainedAnchors']
    fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='retained']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
        and v.value=='DISCOVERY_FROZEN_SOURCE_ANCHOR_MATCHES_RETAINED_RAW_BASIS' for v in ast.walk(n)))]
    scope=dict(vars(anchors));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual-source-basis-guard-removed>','exec'),scope)
    got=scope['retained'](c,buffer(),prior(),'SYNTHETIC',['2018-01-02',99.,13.])
    assert got.raw_close==12.5;c.stream.close()

def test_schema_rejects_nonpositive_or_nonfinite_actual_observation(tmp_path):
    c=cache(tmp_path)
    with pytest.raises(ValueError):c.store(source_bar(raw=float('nan')),'FROZEN_SOURCE_PACKET')
    with pytest.raises(ValueError):c.store(source_bar(raw=0.),'FROZEN_SOURCE_PACKET')
    c.stream.close()
