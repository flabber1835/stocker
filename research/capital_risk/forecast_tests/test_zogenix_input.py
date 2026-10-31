"""Pure input/guard checks. Canonical integration is hosted only."""
from dataclasses import dataclass,asdict,replace
import hashlib,inspect,json,subprocess,sys,textwrap
from pathlib import Path
from types import SimpleNamespace
import pytest
from system_campaign_zogenix_input import InputCodec,parse,require_no_position,SID,NATIVE,DAY,SCHEMA
from system_campaign_zogenix_sensor import material,inherited_witness,check_inherited
import system_campaign_uncertainty_context as old
from system_campaign_uncertainty_math import Interval


@dataclass(frozen=True)
class Term:
    session:str=NATIVE
    security_id:str=SID
    cash_per_share:float|None=None

@dataclass(frozen=True)
class Packet:
    day:str
    terminal:tuple
    bars:tuple=('unchanged-test-quote',)


def native_sha(term):
    return hashlib.sha256(json.dumps(asdict(term),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def document():
    return dict(schema=SCHEMA,predecessor_checkpoint_sha256='a'*64,native_session=NATIVE,session=DAY,
        security_id=SID,native_term_sha256=native_sha(Term()),sensor_only=True,require_unowned_and_unordered=True,
        consideration_range='26<=cash_plus_nontransferable_right<=28',
        treatment='RECALENDAR_INCOMPLETE_TERM_AND_CERTIFY_ALL_COMPARISONS',
        source_evidence=[dict(reference=f'test:{n}',description='test evidence',sha256=str(n)*64) for n in range(6)])


def load(tmp_path,doc=None,**kwargs):
    doc=document() if doc is None else doc;p=tmp_path/'input.json';p.write_text(json.dumps(doc))
    options=dict(resume_session='2022-02-28',predecessor_checkpoint_sha256='a'*64,
        expected_evidence=document()['source_evidence'],native_sha256=native_sha(Term()))
    options.update(kwargs)
    return parse(p,**options)


def test_exact_distinct_type_and_native_earliest_boundary(tmp_path):
    obj=load(tmp_path)
    assert obj.earliest_affected_session==NATIVE and obj._resume_session=='2022-02-28'
    assert obj.sha256 and not hasattr(obj,'add') and not hasattr(obj,'suppress')


@pytest.mark.parametrize('change',[{'predecessor_checkpoint_sha256':'b'*64},{'sensor_only':False},
    {'sensor_only':1},{'require_unowned_and_unordered':False},{'security_id':'other'},
    {'native_session':DAY},{'session':'2022-03-08'},{'cash_per_share':26.},
    {'consideration_range':'26<=cash_plus_nontransferable_right<=26'},{'add':[]},
    {'native_term_sha256':'0'*64}])
def test_wrong_scope_or_fabricated_value_refuses(tmp_path,change):
    with pytest.raises(ValueError):load(tmp_path,{**document(),**change})


def test_wrong_source_and_consumed_guard(tmp_path):
    with pytest.raises(ValueError,match='UNCONSUMED'):load(tmp_path,resume_session=NATIVE)
    with pytest.raises(ValueError,match='EXACT_NATIVE_AND_EVIDENCE'):load(tmp_path,expected_evidence=[])
    with pytest.raises(ValueError,match='EXACT_NATIVE_AND_EVIDENCE'):load(tmp_path,native_sha256='0'*64)


def codec(tmp_path):
    doc=document();path=tmp_path/'input.json';path.write_text(json.dumps(doc))
    obj=InputCodec(doc['source_evidence'],Term())
    loaded=obj.load(path,resume_session='2022-02-28',predecessor_checkpoint_sha256='a'*64)
    return obj,loaded


def test_calendar_moves_only_the_incomplete_term_and_preserves_quotes(tmp_path):
    obj,loaded=codec(tmp_path);other=Term(security_id='OTHER')
    packet=Packet(NATIVE,(Term(),other));before=asdict(packet);changed=obj.apply(packet,loaded)
    assert asdict(packet)==before and changed.terminal==(other,) and changed.bars==packet.bars
    effective=Packet(DAY,(other,));changed=obj.apply(effective,loaded)
    assert changed.terminal==(other,Term(session=DAY)) and changed.terminal[-1].cash_per_share is None
    unchanged=Packet('2022-03-03',());assert obj.apply(unchanged,loaded) is unchanged


def test_wrong_native_collision_or_unadmitted_object_refuses(tmp_path):
    obj,loaded=codec(tmp_path)
    for packet in (Packet(NATIVE,()),Packet(NATIVE,(Term(cash_per_share=26.),)),Packet(DAY,(Term(session=DAY),))):
        with pytest.raises(ValueError):obj.apply(packet,loaded)
    other=load(tmp_path)
    with pytest.raises(ValueError,match='ONLY_EXACT_ADMITTED'):obj.apply(Packet(NATIVE,(Term(),)),other)


def test_ordinary_parser_is_not_relaxed(tmp_path):
    obj=InputCodec(document()['source_evidence'],Term());calls=[]
    def strict(*args,**kwargs):calls.append(1);raise ValueError('ordinary empty input refused')
    obj.original_load=strict;p=tmp_path/'ordinary.json';p.write_text(json.dumps(dict(schema='terminal-repair/1',add=[],suppress=[])))
    with pytest.raises(ValueError,match='ordinary empty'):
        obj.load(p,resume_session='2022-02-28',predecessor_checkpoint_sha256='a'*64)
    assert calls==[1]


def test_actual_position_scope_and_guard_removal_falsifier():
    empty=SimpleNamespace(wealth_core={'episodes':{}},pending=[]);require_no_position(empty)
    owned=SimpleNamespace(wealth_core={'episodes':{'0':{'security_id':SID}}},pending=[])
    pending=SimpleNamespace(wealth_core={'episodes':{}},pending=[{'security_id':SID}])
    for prior in (owned,pending):
        with pytest.raises(ValueError,match='MUST_NOT_BE_'):require_no_position(prior)
    raw=textwrap.dedent(inspect.getsource(require_no_position))
    broken=raw.replace("and v['security_id']!=SID for v in episodes.values()","for v in episodes.values()")
    assert raw!=broken;scope={};exec(broken,require_no_position.__globals__,scope)
    scope['require_no_position'](owned)  # Test detects the real lost protection.


def test_inherited_code_is_identical_and_original_globals_are_unchanged():
    assert material.__code__ is old.return_material.__code__
    assert inherited_witness.__code__ is old.SensorCertificate.witness.__code__
    assert old.SID=='941065113449292610' and material.__globals__ is not old.return_material.__globals__
    state={'selected':[SID,old.SID],'selected_closes':{SID:28.,old.SID:20.}}
    rows,_=material(state,{}, {SID:26.,old.SID:20.},Interval(26.,28.))
    assert rows[0]['current']==[26.,28.] and rows[1]['current']==[20.,20.]
    check_inherited()


def test_source_hash_guard_is_effective(monkeypatch):
    original=Path.read_bytes
    def altered(path):
        raw=original(path)
        return raw+b'\n# changed' if path.name=='system_campaign_uncertainty_math.py' else raw
    monkeypatch.setattr(Path,'read_bytes',altered)
    with pytest.raises(ValueError,match='UNCHANGED_QUALIFIED'):check_inherited()


def test_transfer_job_import_needs_no_financial_runtime():
    code='''
import builtins,sys
sys.path.insert(0,'research/capital_risk')
original=builtins.__import__
def restricted(name,*a,**k):
    if name.split('.')[0] in {'pydantic','numpy','pandas','sentinel','research'}:
        raise ImportError('blocked replay dependency:'+name)
    return original(name,*a,**k)
builtins.__import__=restricted
import system_campaign_p02_zogenix_job
'''
    subprocess.run([sys.executable,'-B','-c',textwrap.dedent(code)],check=True,capture_output=True,text=True,timeout=30)


def test_new_request_closure_and_every_inherited_driver_byte():
    import system_campaign_p02_zogenix_job as job
    from forecast_tests.test_basis_job_sources import dependencies
    root=Path(__file__).resolve().parents[1]
    request=job.expected_request()
    assert request==json.loads((root/'system-campaign-p02-zogenix-request.json').read_bytes())
    assert not dependencies(job.SOURCES)-set(job.SOURCES)
    old=json.loads((root/'system-campaign-p02-february-request.json').read_bytes())
    assert all(request['sources'][k]==v for k,v in old['sources'].items())
    spec=json.loads((root/request['predecessor_file']).read_bytes())
    assert spec['selected_session']=='2022-02-28' and spec['outer_sha256']=='8229aea8c5b038ff54dd475d24cfe8738892ed0747ad7f342a92dcd493ce1743'
    assert len(spec['repairs'])==26 and request['only_candidate']=='P02' and not request['new_origin']
    assert request['canonical_controller_sources']==old['canonical_controller_sources']
