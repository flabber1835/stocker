"""Pure input/guard checks. Canonical integration is hosted only."""
from dataclasses import dataclass,asdict,replace
import hashlib,inspect,json,subprocess,sys,textwrap
from pathlib import Path
from types import SimpleNamespace
import pytest
from system_campaign_abiomed_input import InputCodec,parse,require_no_position,SID,NATIVE,DAY,SCHEMA
from system_campaign_abiomed_sensor import material,inherited_witness,check_inherited
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
        consideration_range='380<=cash_plus_nontransferable_right<=415',
        treatment='RECALENDAR_INCOMPLETE_TERM_AND_CERTIFY_ALL_COMPARISONS',
        source_evidence=[dict(reference=f'test:{n}',description='test evidence',sha256=str(n)*64) for n in range(6)])


def load(tmp_path,doc=None,**kwargs):
    doc=document() if doc is None else doc;p=tmp_path/'input.json';p.write_text(json.dumps(doc))
    options=dict(resume_session='2022-11-30',predecessor_checkpoint_sha256='a'*64,
        expected_evidence=document()['source_evidence'],native_sha256=native_sha(Term()))
    options.update(kwargs)
    return parse(p,**options)


def test_exact_distinct_type_and_native_earliest_boundary(tmp_path):
    obj=load(tmp_path)
    assert obj.earliest_affected_session==NATIVE and obj._resume_session=='2022-11-30'
    assert obj.sha256 and not hasattr(obj,'add') and not hasattr(obj,'suppress')


@pytest.mark.parametrize('change',[{'predecessor_checkpoint_sha256':'b'*64},{'sensor_only':False},
    {'sensor_only':1},{'require_unowned_and_unordered':False},{'security_id':'other'},
    {'native_session':DAY},{'session':'2022-12-23'},{'cash_per_share':26.},
    {'consideration_range':'380<=cash_plus_nontransferable_right<=380'},{'add':[]},
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
    loaded=obj.load(path,resume_session='2022-11-30',predecessor_checkpoint_sha256='a'*64)
    return obj,loaded


def test_calendar_moves_only_the_incomplete_term_and_preserves_quotes(tmp_path):
    obj,loaded=codec(tmp_path);other=Term(security_id='OTHER')
    packet=Packet(NATIVE,(Term(),other));before=asdict(packet);changed=obj.apply(packet,loaded)
    assert asdict(packet)==before and changed.terminal==(other,) and changed.bars==packet.bars
    effective=Packet(DAY,(other,));changed=obj.apply(effective,loaded)
    assert changed.terminal==(other,Term(session=DAY)) and changed.terminal[-1].cash_per_share is None
    unchanged=Packet('2022-12-20',());assert obj.apply(unchanged,loaded) is unchanged


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
        obj.load(p,resume_session='2022-11-30',predecessor_checkpoint_sha256='a'*64)
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
    state={'selected':[SID,old.SID],'selected_closes':{SID:415.,old.SID:20.}}
    rows,_=material(state,{}, {SID:380.,old.SID:20.},Interval(380.,415.))
    assert rows[0]['current']==[380.,415.] and rows[1]['current']==[20.,20.]
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
import system_campaign_p02_abiomed_job
'''
    subprocess.run([sys.executable,'-B','-c',textwrap.dedent(code)],check=True,capture_output=True,text=True,timeout=30)




def test_duplicate_scope_key_is_not_silently_accepted(tmp_path):
    raw=json.dumps(document());raw=raw[:-1]+',"sensor_only":true}'
    path=tmp_path/'duplicates.json';path.write_text(raw)
    with pytest.raises(ValueError,match='DUPLICATE_INPUT_KEY'):
        parse(path,resume_session='2022-11-30',predecessor_checkpoint_sha256='a'*64,
              expected_evidence=document()['source_evidence'],native_sha256=native_sha(Term()))


def test_actual_new_post_guard_and_its_removal_falsifier():
    from system_campaign_abiomed_sensor import SensorCertificate,PriorCertificate
    before=SimpleNamespace(wealth_core={'episodes':{}},pending=[])
    after=SimpleNamespace(wealth_core={'episodes':{'x':{'security_id':SID}}},pending=[])
    probe=SensorCertificate.__new__(SensorCertificate);probe.math=None
    probe.original_advance=lambda run,published:SimpleNamespace(state=after)
    run=SimpleNamespace(state=before);published=SimpleNamespace(session=DAY)
    with pytest.raises(ValueError,match='MUST_NOT_BE_OWNED'):probe.advance(run,published)
    assert PriorCertificate.advance(probe,run,published).state is after


def test_existing_guarded_input_binding_uses_its_descriptor_not_latest_cursor():
    import ast
    import system_campaign_abiomed_facts as facts
    text=Path(facts.__file__).read_text()
    assert "body = expected_repair(target, descriptor['predecessor_checkpoint_sha256'])" in text
    assert "expected_repair(target, cp['run']['checkpoint_sha256'])" not in text


def test_single_own_continuation_and_frozen_inherited_source_metadata():
    import system_campaign_p02_abiomed_job as job
    root=Path(job.__file__).parent
    request=json.loads((root/'system-campaign-p02-abiomed-request.json').read_bytes())
    old_request=json.loads((root/'system-campaign-p02-october-recovery-request.json').read_bytes())
    assert len(job.SOURCES)==177 and set(old_request['sources'])<=set(request['sources'])
    assert all(request['sources'][name]==value for name,value in old_request['sources'].items())
    spec=json.loads((root/request['predecessor_file']).read_bytes())
    assert spec['run_id']==41166283025 and spec['selected_session']=='2022-11-30'
    assert spec['outer_sha256']=='210531c3a3ad25e903ecb6601efd28ce4114ff33c54bc216ac9ba092ed7e682e'
    assert len(spec['repairs'])==28 and spec['parent_certificate_rows']==784
    assert request['only_candidate']=='P02' and request['concurrent_candidate_limit']==1 and not request['new_origin']
    text=(root/'system_campaign_p02_abiomed_run.py').read_text()
    assert text.count('backtest.main, args')==1 and "arguments(out / 'book', True)" in text
    assert text.index("timing.call('actual_merged_abiomed_canonical_gate'")<text.index("timing.call('financial_driver_total'")
    assert 'runtime.start(' not in text


def test_guard_suffix_keeps_real_preceding_financial_context(tmp_path, monkeypatch):
    import system_campaign_abiomed_review as reviewer
    from system_campaign_completion_scope import WATCH, SCOPE, active, digest, projection, review_guards
    def row(day):
        accounting={'wealth_core':{'episodes':{}},'pending':[]}
        return {'session':day,'state_sha256':digest(day),'input_sha256':'b'*64,
                'evidence':{'research_entry_audit':{'opening_accounting':accounting,
                    'closing_accounting':accounting},'wealth_core':{'intents':[]}}}
    financial=[row(day) for day in ['2022-10-03','2022-10-04','2022-10-05']]
    watches=[]
    for previous,current in zip(financial,financial[1:]):
        before=previous['evidence']['research_entry_audit']['closing_accounting']
        after=current['evidence']['research_entry_audit']['closing_accounting'];names=active(current['session'])
        watches.append(dict(schema=WATCH,session=current['session'],scope=SCOPE,
            affected_security_ids=names,guarded_input_sha256='c'*64,input_sha256=current['input_sha256'],
            prior_state_sha256=previous['state_sha256'],next_state_sha256=current['state_sha256'],
            before=projection(before['wealth_core'],before['pending'],names),
            after=projection(after['wealth_core'],after['pending'],names),financial_row_sha256=digest(current)))
    prior=review_guards(financial[:2],watches[:1],guarded_input_sha256='c'*64)
    old=tmp_path/'old';root=tmp_path/'new';old.mkdir();root.mkdir()
    raw=json.dumps(prior).encode();(old/'completion-position-guard-review.json').write_bytes(raw)
    (root/'parent-completion-position-guard-review.json').write_bytes(raw)
    monkeypatch.setattr(reviewer,'validate_completion',lambda root,cp:[SimpleNamespace(sha256='c'*64)])
    monkeypatch.setattr(reviewer,'committed_rows',lambda *args:watches)
    parent={'source_cursor':'2022-10-04','run':{'state':{'wealth_core':{'episodes':{}},'pending':[]}}}
    result=reviewer.review_positions(root,old,{},parent,{r['session']:r for r in financial})
    assert result['rows']==2
    # A suffix-only call loses its required predecessor and must not pass.
    with pytest.raises(ValueError):review_guards(financial[2:],watches[1:],guarded_input_sha256='c'*64)


def unadvanced_function(remove_byte_guard=False):
    import ast
    from full_system_benchmark import need,save
    root=Path(__file__).resolve().parents[1]
    tree=ast.parse((root/'system_campaign_p02_abiomed_run.py').read_bytes())
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='unadvanced_parent']
    if remove_byte_guard:
        loop,=[n for n in fn.body if isinstance(n,ast.For) and isinstance(n.iter,ast.Name)
               and n.iter.id=='names']
        guard,=[n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
                and any(isinstance(a,ast.Constant) and a.value=='ABIOMED_UNADVANCED_COMPLETE_ORIGINAL_BYTES'
                        for a in n.value.args)]
        loop.body.remove(guard)
    namespace={'need':need,'save':save,'sha':lambda raw:hashlib.sha256(raw).hexdigest()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<actual-unadvanced-metadata-helper>', 'exec'),namespace)
    return namespace['unadvanced_parent']


def unchanged_files(tmp_path):
    old=tmp_path/'old';new=tmp_path/'new';out=tmp_path/'review'
    for root in [old,new,out]:root.mkdir()
    cp={'sha256':'a'*64,'journals':{n:{} for n in ['daily','formation','monthly','watch']}}
    for name in ['book/checkpoint.json.gz','book/identity.json','source-bindings.json',
                 *['book/'+n+'.jsonl' for n in cp['journals']]]:
        for root in [old,new]:
            p=root/name;p.parent.mkdir(exist_ok=True);p.write_bytes(('exact-'+name).encode())
    spec={'outer_sha256':cp['sha256']}
    for name,key in [('core-review.json','review_sha256'),
                     ('uncertainty-certificate-review.json','interval_review_sha256')]:
        raw=b'{"trusted_parent":true}';(old/name).write_bytes(raw);spec[key]=hashlib.sha256(raw).hexdigest()
    for name in ['completion-position-guard-review.json','common-factual-and-uncertainty-basis.json']:
        (old/name).write_bytes(b'{}')
    return out,new,old,spec,cp


def test_unadvanced_parent_reuses_only_full_identical_bytes(tmp_path):
    out,new,old,spec,cp=unchanged_files(tmp_path)
    unadvanced_function()(out,new,old,spec,cp,cp)
    proof=json.loads((out/'unadvanced-parent-review.json').read_bytes())
    assert proof['actual_new_financial_rows']==0 and not proof['abiomed_gate_or_model_adoption_claimed']


def test_unsent_tail_difference_refuses_old_proof_and_guard_removal_is_detected(tmp_path):
    out,new,old,spec,cp=unchanged_files(tmp_path)
    with (new/'book/daily.jsonl').open('ab') as f:f.write(b'new-unsent-tail')
    with pytest.raises(ValueError,match='COMPLETE_ORIGINAL_BYTES'):
        unadvanced_function()(out,new,old,spec,cp,cp)
    unadvanced_function(remove_byte_guard=True)(out,new,old,spec,cp,cp)
    assert (out/'unadvanced-parent-review.json').exists()
