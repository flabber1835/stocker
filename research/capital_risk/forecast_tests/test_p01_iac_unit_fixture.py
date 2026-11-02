"""Pure fixture plans and source-shaped stubs; no local canonical execution."""
import ast
from copy import deepcopy
from datetime import date,timedelta
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_fixture_component as c
import p01_iac_unit_fixture_run as run


def protected(wealth,pending):
    ids={e['security_id'] for e in wealth['episodes'].values()}
    ids.update(s[k] for s in wealth['slots'].values() for k in ('occupied_by','reserved_for') if s.get(k))
    ids.update(p['security_id'] for p in pending)
    for key in ('security_cooldowns','unresolved_terminals','sessions_since_valid_mark','terminal_pending_sessions',
                'terminal_pending_terms','terminal_carry_audit','last_valid_mark_session'):
        ids.update(wealth.get(key,{}))
    return ids


class Slot:
    def __init__(self):self.occupied_by=None;self.reserved_for=None;self.reserved_ticker=None;self.reserved_issuer=None
    def reserve(self,sid,ticker,issuer):self.reserved_for=sid;self.reserved_ticker=ticker;self.reserved_issuer=issuer


class Book:
    def __init__(self,cash,n_slots):
        self.cash=cash;self.slots={i:Slot() for i in range(n_slots)};self.episodes={}
        self.entry_sizing_profile=None;self.median5={}
    @classmethod
    def fresh(cls,cash,*,n_slots):return cls(cash,n_slots)
    def to_dict(self):
        return dict(cash=self.cash,slots={str(k):vars(v).copy() for k,v in self.slots.items()},
            episodes={str(k):vars(v).copy() for k,v in self.episodes.items()},entry_sizing_profile=self.entry_sizing_profile,
            median5=deepcopy(self.median5),**{k:{} for k in ('security_cooldowns','unresolved_terminals','sessions_since_valid_mark',
                'terminal_pending_sessions','terminal_pending_terms','terminal_carry_audit','last_valid_mark_session')})


class Ledger:
    def __init__(self):self.events=[]
    def post(self,**kwargs):self.events.append(dict(kwargs,cash_after=kwargs['cash_before']+kwargs['cash_delta']))
    def to_dict(self):return dict(events=deepcopy(self.events),receivables=[])


class PendingOrder:
    def __init__(self,operation,security_id,ticker,slot_id,shares,signal_session,reason,*,intended_dollars=None):
        self.values=dict(operation=operation,security_id=security_id,ticker=ticker,slot_id=slot_id,shares=shares,
            signal_session=signal_session,reason=reason,intended_dollars=intended_dollars)
    def to_dict(self):return self.values.copy()


class Series:
    def __init__(self,security_id,ticker,issuer_id):
        self.security_id=security_id;self.ticker=ticker;self.issuer_id=issuer_id;self.split_factor=1.
        self.sessions=[];self.session_indices=[];self.signal_closes=[];self.raw_closes=[];self.volumes=[];self.signal_basis_anchor=None
    def append(self,bar,index,*,published_signal=False):
        assert published_signal
        self.split_factor*=bar.split_ratio;self.split_factor=bar.signal_close/bar.raw_close
        self.sessions.append(bar.session);self.session_indices.append(index);self.signal_closes.append(bar.signal_close)
        self.raw_closes.append(bar.raw_close);self.volumes.append(bar.volume)
        self.signal_basis_anchor=[bar.session,bar.raw_close,bar.signal_close]


class VendorBar:
    def __init__(self,session,security_id,ticker,raw_close,raw_open,volume,*,split_ratio=1.,signal_close=None):
        self.session=session;self.security_id=security_id;self.ticker=ticker;self.raw_close=raw_close
        self.raw_open=raw_open;self.volume=volume;self.split_ratio=split_ratio;self.signal_close=signal_close


class Feed:
    def __init__(self,raw):self._session_index=raw['session_index'];self._seen_sessions={};self.series={}
    def _advance_session(self,day):
        assert day not in self._seen_sessions;self._session_index+=1;self._seen_sessions[day]=self._session_index;return self._session_index


def from_feed(raw,meta,elig):return Feed(raw)


def to_feed(feed,ids):
    return dict(history_sessions=260,session_index=feed._session_index,seen_sessions=deepcopy(feed._seen_sessions),
        series={sid:deepcopy(vars(series)) for sid,series in feed.series.items()})


class Session:
    """Schema-shaped stub, NOT the actual canonical SessionState serializer."""
    @classmethod
    def from_dict(cls,wire):
        ids=protected(wire['wealth_core'],wire['pending']);registry=wire['feed']['series']
        if not ids<=set(registry):raise ValueError('STUB_SCHEMA_MISSING_PROTECTED_FEED_ANCHORS')
        assert wire['feed']['history_sessions']==260 and len(wire['wealth_core']['slots'])==30
        for sid in ids:
            value=registry[sid]
            assert value['security_id']==sid and value['ticker'] and value['issuer_id']
            assert len({len(value[k]) for k in ('sessions','session_indices','signal_closes','raw_closes','volumes')})==1
            assert value['session_indices'][-1]<=wire['feed']['session_index']
        out=deepcopy(wire);out['last_known']={k:v for k,v in out['last_known'].items() if k in ids}
        return SimpleNamespace(to_dict=lambda:deepcopy(out))


def entry_cost(shares,price,cfg):return shares*price+shares*price*.001


def apply_entry(book,*,op,session,signal_session,raw_open,split_adjusted_price,issuer_id,cfg):
    book.cash-=entry_cost(op.shares,raw_open,cfg)
    book.episodes[op.slot_id]=SimpleNamespace(security_id=op.security_id,ticker=op.ticker,issuer_id=issuer_id,
        current_shares=op.shares,initial_shares=op.shares,exit_pending=False,entry_session=session,signal_session=signal_session)
    book.slots[op.slot_id].occupied_by=op.security_id


ENGINE=SimpleNamespace(entry_cost=entry_cost,apply_entry=apply_entry,Op=lambda operation,reason,**kw:SimpleNamespace(**kw),
    Operation=SimpleNamespace(OPEN_SLOT_POSITION='OPEN_SLOT_POSITION',CLOSE_POSITION='CLOSE_POSITION'))
STATE=SimpleNamespace(PortfolioState=Book);LEDGER=SimpleNamespace(Ledger=Ledger,EventType=SimpleNamespace(BUY='BUY'))
ADAPTER=SimpleNamespace(PendingOrder=PendingOrder);FEED=SimpleNamespace(SecuritySeries=Series,VendorBar=VendorBar)
CFG=SimpleNamespace(n_slots=30)


def base(day='2020-06-30'):
    cursor=date.fromisoformat(day);days=[]
    while len(days)<260:
        if cursor.weekday()<5:days.append(cursor.isoformat())
        cursor-=timedelta(days=1)
    days.reverse();book=Book.fresh(50000.,n_slots=30);book.entry_sizing_profile='SYNTHETIC_FIXED_PROFILE'
    value=dict(last_processed_session=day,wealth_core=book.to_dict(),pending=[],ledger=Ledger().to_dict(),last_known={},
        controller={'SYNTHETIC_UNCHANGED':1},feed=dict(history_sessions=260,session_index=1259,
            seen_sessions={d:1000+i for i,d in enumerate(days)},series={}))
    plan=c.fixture_plan(value,c.SOURCE if day==c.EVENT else c.CHILD,'DOLLAR_BUY_PENDING',signal_session=day)
    value['feed']=c.planned_feed(plan)
    # Old fixture has source observations only, mirroring the exact absent-target
    # interface condition. No market observation is used in this test.
    value['feed']['series']={c.SOURCE:value['feed']['series'][c.SOURCE]}
    return value


def construct(value,target,role,**kw):
    return c.make_fixture(value,target,role,CFG,STATE,LEDGER,ENGINE,ADAPTER,FEED,Session,
        from_feed,to_feed,protected,None,signal_session=value['last_processed_session'],**kw)


@pytest.mark.parametrize('target',[c.CHILD,c.OLD_MATCH])
@pytest.mark.parametrize('role',c.ROLES)
def test_every_old_actual_fixture_function_exposes_missing_protected_anchor(target,role):
    tree=ast.parse((HERE/'p01_iac_unit_component.py').read_bytes())
    outer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_components')
    fn=next(n for n in outer.body if isinstance(n,ast.FunctionDef) and n.name=='fixture')
    ns=dict(template=base(),state=STATE,ledger=LEDGER,engine=ENGINE,adapter=ADAPTER,cfg=CFG,
        deepcopy=deepcopy,SessionState=Session,SOURCE=c.SOURCE,need=c.need)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<actual-old-fixture-shaped-stubs>','exec'),ns)
    with pytest.raises(ValueError,match='MISSING_PROTECTED_FEED_ANCHORS'):ns['fixture'](target,role)


@pytest.mark.parametrize('case',c.CASE_IDS)
def test_all_nine_complete_contexts_preserve_exact_calendar_and_unrelated_fields(case):
    post=case=='POST_EVENT_SOURCE_BUY';target=c.SOURCE if post else case.split('/')[0]
    role='DOLLAR_BUY_PENDING' if post else case.split('/')[1];value=base(c.EVENT if post else '2020-06-30')
    original=deepcopy(value);captures=[]
    wire,ticker,issuer,contract=construct(value,target,role,capture=lambda stage,raw:captures.append((stage,raw)))
    assert value==original and captures and wire['feed']==c.planned_feed(contract['plan'])
    assert contract['protected_security_ids']==sorted(protected(wire['wealth_core'],wire['pending']))
    assert set(wire['feed']['series'])==({c.SOURCE} if post else {c.SOURCE,target})
    assert wire['feed']['seen_sessions']==value['feed']['seen_sessions']
    assert wire['feed']['session_index']==1259 and wire['last_processed_session']==value['last_processed_session']
    assert wire['controller']==original['controller']
    assert ticker==contract['plan']['instruments'][target]['ticker'] and issuer==contract['plan']['instruments'][target]['issuer_id']
    assert wire['last_known'][target]==10. and (not post or wire['pending'][0]['signal_session']==c.EVENT)
    assert contract['plan']['market_observations_or_preIPO_evidence'] is False


def test_actual_new_build_feed_guard_rejects_missing_series_and_removed_guard_falsifier():
    value=base();plan=c.fixture_plan(value,c.CHILD,'HELD',signal_session=value['last_processed_session'])
    def bad_to_feed(context,ids):
        raw=to_feed(context,ids);raw['series'].pop(c.CHILD);return raw
    with pytest.raises(ValueError,match='ENTIRE_SYNTHETIC_FEED'):c.build_feed(plan,FEED,from_feed,bad_to_feed,{c.CHILD},None)
    tree=ast.parse(Path(c.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_feed')
    fn.body=[n for n in fn.body if not any(isinstance(k,ast.Constant)
        and k.value=='ENTIRE_SYNTHETIC_FEED_CANONICAL_APIS_MATCH_DECLARED_PLAN' for k in ast.walk(n))]
    ns=dict(vars(c));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-feed-contract-guard>','exec'),ns)
    assert c.CHILD not in ns['build_feed'](plan,FEED,from_feed,bad_to_feed,{c.CHILD},None)['series']


def test_aggregate_retains_all_nine_attempts_even_with_early_and_late_failures():
    proof={'fixture_aggregate':c.aggregate()}
    for index,case in enumerate(c.CASE_IDS):
        c.finish_case(proof,case,stage='SYNTHETIC_TEST',error=ValueError('SYNTHETIC_REFUSAL') if index in (0,8) else None)
    result=proof['fixture_aggregate']
    assert result['complete'] is True and result['all_passed'] is False
    assert result['attempted_case_ids']==list(c.CASE_IDS) and len(result['passed_case_ids'])==7 and len(result['failed_cases'])==2


def cp(day):
    state={'last_processed_session':day,'source':{'numeric':1}}
    run=dict(state=state,state_sha256=c.digest(state),input_sha256='f'*64);run['checkpoint_sha256']=c.digest(run);return run


def boundary():
    zero=dict(run=cp('2020-06-30'),completed=628,source_cursor='2020-06-30');zero['sha256']=c.digest(zero)
    paths=[];prior=zero['run']
    for day in c.FIRST:
        current=cp(day);paths.append(dict(session=day,prior_checkpoint=deepcopy(prior),publication={'session':day},checkpoint=current));prior=current
    final=dict(run=prior,completed=630,source_cursor=c.FIRST[-1]);final['sha256']=c.digest(final)
    return zero,paths,final


@pytest.mark.parametrize('kind',['prior_numeric_type','zero_outer','final_outer','zero_runtime'])
def test_reference_boundary_keeps_complete_hashed_objects_exact(kind):
    zero,paths,final=boundary();assert c.reference_boundary(paths,final,zero,{})['financial_authority'] is False
    if kind=='prior_numeric_type':paths[0]['prior_checkpoint']['state']['source']['numeric']=1.0
    if kind=='zero_outer':zero['completed']=627
    if kind=='final_outer':final['completed']=629
    if kind=='zero_runtime':zero['run']['state']['source']['numeric']=2;zero['sha256']=c.digest({k:v for k,v in zero.items() if k!='sha256'})
    with pytest.raises(ValueError):c.reference_boundary(paths,final,zero,{})


def test_new_actual_runtime_forwards_reference_before_component_and_uses_new_module():
    fn=run._body('branch')
    assert fn.__globals__['qualify_components'] is c.qualify_components
    assert set(('reference_components','qualifier_checkpoint','input_zero_checkpoint'))<=set(k for value in fn.__code__.co_consts if isinstance(value,tuple) for k in value if isinstance(k,str))
    assert 'p01_iac_unit_fixture_review' in run._body('main').__code__.co_names


def test_every_fixture_plan_and_constructor_is_inside_per_case_failure_scope():
    tree=ast.parse(Path(c.__file__).read_bytes());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_components')
    loop=next(n for n in fn.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='CASE_IDS')
    handler=next(n for n in loop.body if isinstance(n,ast.Try))
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='fixture_plan' for n in ast.walk(handler))
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='make_fixture' for n in ast.walk(handler))
    assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='finish_case' for n in ast.walk(handler.handlers[0]))
    first_save=next(n.lineno for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and isinstance(n.value.func,ast.Name) and n.value.func.id=='write_progress')
    reference=next(n.lineno for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='reference_boundary')
    assert reference<first_save<loop.lineno


def test_actual516_feed_constructor_field_shapes_and_mutable_mark_callsite():
    import json
    mapping=json.loads((HERE/'p01_celg_bridge_source_map.json').read_bytes())['successor_all_sources']
    root=Path('C:/Users/mbron/.codex/visualizations/2026/10/25/01a1737f-f4e0-7cf1-990e-82ae645d665b/research-capital-risk-20261027/system-optimization-002/p01-sequential-001')
    def ext(path):return Path('\\\\?\\'+str(path.resolve())) if sys.platform=='win32' else path
    names={
        'shared/stock_strategy_shared/wealth_core/feed.py':root/'native-resume-001/source-semantics-516/shared__stock_strategy_shared__wealth_core__feed.py.txt',
        'sentinel/core/session.py':root/'action-research/iac-mtch-primary-20200701-001/normalizer-contract-source-516/sentinel__core__session.py.txt'}
    trees={}
    for name,path in names.items():
        raw=ext(path).read_bytes();assert c.sha(raw)==mapping[name];trees[name]=ast.parse(raw)
    feed=trees['shared/stock_strategy_shared/wealth_core/feed.py']
    fields=lambda name:[n.target.id for node in feed.body if isinstance(node,ast.ClassDef) and node.name==name
        for n in node.body if isinstance(n,ast.AnnAssign)]
    assert fields('VendorBar')==['session','security_id','ticker','raw_close','raw_open','volume','split_ratio',
        'dividend_per_share','tradeable','unresolved_corporate_action','signal_close']
    assert fields('SecuritySeries')==['security_id','ticker','issuer_id','split_factor','sessions','session_indices',
        'signal_closes','raw_closes','volumes','vendor_basis_multiplier','signal_basis_multiplier','signal_basis_anchor']
    cls=next(n for n in feed.body if isinstance(n,ast.ClassDef) and n.name=='Feed')
    advance=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_advance_session')
    assert [a.arg for a in advance.args.args]==['self','session']
    session=trees['sentinel/core/session.py']
    expected={'_feed_from_dict':['raw','meta','elig'],'_feed_to_dict':['feed','protected_security_ids'],
        '_path_dependent_security_ids':['wealth_core','pending']}
    for name,args in expected.items():
        fn=next(n for n in session.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert [a.arg for a in fn.args.args]==args
    tree=ast.parse(Path(c.__file__).read_bytes());outer=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_components')
    assignments=[ast.unparse(n) for n in ast.walk(outer) if isinstance(n,ast.Assign)]
    assert assignments.count('result.last_known = marks')==1 and assignments.count('full.last_known = marks')==1
    assert c.PHASE=='ACTIONS_FILLS_CLOSE_PRE_DECISION_NOT_A_COMPLETE_SESSION'


def test_real_source_normalizer_body_is_exact_old_ast_not_a_fixture_price_repair():
    def segment(path):
        fn=next(n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_components')
        start=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='rows' for t in n.targets))
        stop=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prefix' for t in n.targets))
        return ast.dump(ast.Module(body=fn.body[start:stop],type_ignores=[]),include_attributes=False)
    assert segment(Path(c.__file__))==segment(HERE/'p01_iac_unit_component.py')


def test_raw_fixture_is_captured_before_canonical_constructor_refusal():
    class Refused:
        @classmethod
        def from_dict(cls,wire):raise ValueError('SYNTHETIC_LATER_SCHEMA_REFUSAL')
    records=[];value=base()
    with pytest.raises(ValueError,match='LATER_SCHEMA'):
        c.make_fixture(value,c.CHILD,'HELD',CFG,STATE,LEDGER,ENGINE,ADAPTER,FEED,Refused,
            from_feed,to_feed,protected,None,signal_session=value['last_processed_session'],capture=lambda stage,raw:records.append((stage,raw)))
    assert records[0][0]=='RAW_FIXTURE_BEFORE_CANONICAL_RESTORE'
    assert c.CHILD in records[0][1]['feed']['series'] and records[0][1]['wealth_core']['episodes']


def test_actual_runtime_summary_binds_final_aggregate_proof_and_refuses_failure(tmp_path,monkeypatch):
    import gzip,json
    proof=tmp_path/'proof';proof.mkdir()
    aggregate=c.aggregate()
    for case in c.CASE_IDS:c.finish_case({'fixture_aggregate':aggregate},case,stage='SYNTHETIC_TEST')
    raw=gzip.compress(c.encoded(dict(schema=c.SCHEMA,fixture_aggregate=aggregate)),mtime=0)
    (proof/'unit-normalization-component.json.gz').write_bytes(raw)
    assert run._body('qualify').__globals__['save'] is run.save
    run.save(proof/'qualification-summary.json',{})
    summary=json.loads((proof/'qualification-summary.json').read_bytes())
    assert summary['fixture_expected_case_count']==summary['fixture_attempted_case_count']==summary['fixture_passed_case_count']==9
    assert summary['fixture_failed_case_count']==0 and summary['fixture_component_sha256']==c.sha((proof/'unit-normalization-component.json.gz').read_bytes())
    aggregate['all_passed']=False
    (proof/'unit-normalization-component.json.gz').write_bytes(gzip.compress(c.encoded(dict(schema=c.SCHEMA,fixture_aggregate=aggregate)),mtime=0))
    with pytest.raises(ValueError,match='ALL_NINE_ACTUAL_CANONICAL'):run.save(proof/'qualification-summary.json',{})
