"""Exhaustive-domain, state-set and typed-model falsifiers; no financial replay."""
import ast
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_branches as b
from system_campaign_uncertainty_input import parse as strict_parse


def state():
    return dict(version=2,episode=False,latched=False,full_streak=1,recent_positive_streak=0,
        previous_native=1.,previous_desired=1.,effective_native=1.,champion_audit={'episodes':0,'concordance_releases':0},
        outside='unchanged')


def args(value=-.0007):
    return dict(state=state(),recent_r20=value,recent_r40=-.03)


def recovery(*,state,recent_r20,recent_r40):
    result=deepcopy(state)
    healthy=recent_r20>0 and recent_r40>-.04
    result['full_streak']=min(result['full_streak']+1,8) if healthy else 0
    target=float(result['full_streak']>=8) if result['episode'] else 1.
    result['previous_desired']=target
    return result,dict(desired_allocation=target,reason='synthetic')


def bounds():return dict(recent_r20=b.Interval(-.001,.001),recent_r40=b.Interval.point(-.03))


def test_all_counter_branches_retained_then_propagated_and_merged_without_input_mutation():
    kw=args();saved=deepcopy(kw)
    (actual,decision),possible,leaves=b.cloud(recovery,kw,bounds())
    assert kw==saved and decision==dict(desired_allocation=1.,reason='synthetic')
    assert {r['full_streak'] for r in possible}=={0,2} and len(leaves)==2
    (second,_),following,_=b.cloud(recovery,dict(kw,state=actual,recent_r20=.01),
        dict(recent_r20=b.Interval(.01,.02),recent_r40=b.Interval.point(-.03)),possible)
    assert {r['full_streak'] for r in following}=={1,3}
    (_, _),merged,_=b.cloud(recovery,dict(kw,state=second,recent_r20=-.02),
        dict(recent_r20=b.Interval.point(-.02),recent_r40=b.Interval.point(-.03)),following)
    assert len(merged)==1 and merged[0]['full_streak']==0


@pytest.mark.parametrize('relation',['gt','ge','lt','le'])
def test_exact_threshold_and_adjacent_binary64_values_are_covered_once(relation):
    values=[-.001,math.nextafter(0.,-math.inf),0.,math.nextafter(0.,math.inf),.001]
    pieces=b.split_domain(b.Interval(-.001,.001),0.,relation)
    assert len(pieces)==2
    for v in values:assert sum(p.contains(v) for p in pieces)==1
    fn=getattr(__import__('operator'),relation)
    for piece in pieces:assert fn(piece.lo,0.)==fn(piece.hi,0.)


def test_repeated_contradictory_comparisons_never_create_an_impossible_branch():
    def recover(**kw):
        x=kw['recent_r20'];value=deepcopy(kw['state'])
        result='impossible' if x>0 and x<=0 else 'same'
        return value,dict(reason=result)
    leaves=b.partitions(recover,args(),bounds())
    assert len(leaves)==2 and all(r['decision']==dict(reason='same') for r in leaves)


def test_divergent_actual_decision_refuses_even_if_representative_is_safe():
    kw=args();kw['state'].update(episode=True,full_streak=7)
    with pytest.raises(ValueError,match='BRANCH_FINANCIAL_DECISION_DIFFERS'):b.cloud(recovery,kw,bounds())


def test_same_allocation_with_different_reason_still_refuses():
    def recover(**kw):
        value=deepcopy(kw['state'])
        return value,dict(desired_allocation=1.,reason='positive' if kw['recent_r20']>0 else 'negative')
    with pytest.raises(ValueError,match='BRANCH_FINANCIAL_DECISION_DIFFERS'):b.cloud(recover,args(),bounds())


def test_financial_decision_guard_removal_falsifier():
    kw=args();kw['state'].update(episode=True,full_streak=7)
    with pytest.raises(ValueError):b.cloud(recovery,kw,bounds())
    fn=next(n for n in ast.parse(Path(b.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='cloud')
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='BRANCH_FINANCIAL_DECISION_DIFFERS' for a in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
    remove=Remove();fn=remove.visit(fn);assert remove.count==1;ns=dict(vars(b))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-financial-invariance-guard>','exec'),ns)
    with pytest.raises(AssertionError):
        try:ns['cloud'](recovery,kw,bounds())
        except ValueError:refused=True
        else:refused=False
        assert refused


@pytest.mark.parametrize('limit',['MAX_PARTITIONS','MAX_STATES'])
def test_exploration_bound_refuses_instead_of_truncating_possible_states(monkeypatch,limit):
    monkeypatch.setattr(b,limit,1)
    with pytest.raises(ValueError,match='BOUND_NO_TRUNCATION'):b.cloud(recovery,args(),bounds())


def test_missing_actual_prior_or_modified_noncontroller_fields_refuse():
    kw=args();wrong=b.discrete(kw['state']);wrong['full_streak']=0
    with pytest.raises(ValueError,match='PRIOR_SET_INCLUDES_ACTUAL'):b.cloud(recovery,kw,bounds(),[wrong])
    def changed(**kw):
        value,decision=recovery(**kw);value['outside']='changed';return value,decision
    with pytest.raises(ValueError,match='ONLY_DECLARED_FIELDS'):b.cloud(changed,kw,bounds())
    def mutates(**kw):
        kw['state']['outside']='mutated';return recovery(**kw)
    saved=deepcopy(kw)
    with pytest.raises(ValueError,match='ACTUAL_PRIOR_UNCHANGED'):b.cloud(mutates,kw,bounds())
    assert kw==saved


def test_actual_input_outside_admitted_range_refuses_even_when_decision_matches():
    with pytest.raises(ValueError,match='INPUT_IN_COMPLETE_ADMITTED_DOMAIN'):
        b.cloud(recovery,args(-.02),bounds())


def surfaces():
    # Read only the repository's public frozen controller source. Do not import it.
    root=Path(__file__).resolve().parents[3]
    return (root/'sentinel/controller/champion_frozen.py').read_bytes(),(root/'sentinel/controller/champion.py').read_bytes()


def test_actual_source_has_only_supported_uncertain_comparisons_and_recovery_writes():
    frozen,champion=surfaces();b.qualify_surface(frozen,champion)
    for old,new in [(b'(recent_r20 > 0)',b'(recent_r20 + 0 > 0)'),(b'(recent_r40 > -0.04)',b'(abs(recent_r40) > -0.04)')]:
        assert old in frozen
        with pytest.raises(ValueError,match='ONLY_QUALIFIED_FINITE_CHECKS'):b.qualify_surface(frozen.replace(old,new),champion)
    with pytest.raises(ValueError,match='ONLY_FORWARDS_UNCERTAIN_INPUTS'):
        b.qualify_surface(frozen,champion.replace(b'\n        recent_r20, recent_r40, spy_r20, wc_r20)',b'\n        recent_r20+0, recent_r40, spy_r20, wc_r20)'))


def typed(tmp_path):
    (tmp_path/'hydrated-uncertainty-event.json').write_bytes(b'{"synthetic_event":true}\n')
    cp=dict(source_cursor='2019-09-30',run=dict(checkpoint_sha256='a'*64))
    path=b.overlay(cp,tmp_path)
    return path,cp


def test_new_model_is_distinct_and_old_strict_contract_is_not_relaxed(tmp_path):
    path,cp=typed(tmp_path);ev=b.evidence(tmp_path)
    kw=dict(resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],expected_evidence=ev)
    obj=b.parse(path,**kw)
    assert obj.treatment==b.TREATMENT and obj.sensor_only is obj.require_unowned_and_unordered is True
    with pytest.raises(ValidationError):strict_parse(path,**kw)
    value=json.loads(path.read_bytes());value.update(schema='research.leadership-uncertainty-input/1',treatment='ALL_EXECUTED_COMPARISONS_MUST_BE_INTERVAL_INVARIANT')
    path.write_text(json.dumps(value))
    with pytest.raises(ValidationError):b.parse(path,**kw)


@pytest.mark.parametrize('change',['pred','date','range','owned','scope','evidence'])
def test_new_typed_model_rejects_changed_scope_or_authority(tmp_path,change):
    path,cp=typed(tmp_path);value=json.loads(path.read_bytes());ev=b.evidence(tmp_path)
    if change=='pred':value['predecessor_checkpoint_sha256']='b'*64
    elif change=='date':value['session']='2019-10-23'
    elif change=='range':value['consideration_range']='18<=cash_plus_nontransferable_right<=19'
    elif change=='owned':value['require_unowned_and_unordered']=False
    elif change=='scope':value['security_id']='another'
    else:value['source_evidence'].pop()
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):b.parse(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],expected_evidence=ev)


def proof_fixture(tmp_path):
    book=tmp_path/'book';book.mkdir()
    row=dict(schema=b.SCHEMA,session=b.DAY,input_sha256='a'*64,prior_state_sha256='b'*64,next_state_sha256='c'*64)
    chain=b.digest(dict(previous=b.digest(b.SCHEMA),record=row));row['chain_sha256']=chain
    (tmp_path/'uncertainty-certificate.jsonl').write_bytes(b.encoded(row)+b'\n')
    fin=dict(session=b.DAY,input_sha256='a'*64,state_sha256='c'*64)
    watch=dict(schema=b.WATCH,session=b.DAY,input_sha256='a'*64,next_state_sha256='c'*64,certificate_chain_sha256=chain)
    journals={}
    for name,value in [('formation',None),('daily',fin),('monthly',None),('watch',watch)]:
        raw=b.encoded(value)+b'\n' if value else b'';(book/(name+'.jsonl')).write_bytes(raw)
        journals[name]=dict(bytes=len(raw),prefix_sha256=b.hashlib.sha256(raw).hexdigest())
    return dict(source_cursor=b.DAY,journals=journals),row


def test_entire_certificate_prefix_binds_actual_financial_and_watch_rows(tmp_path):
    cp,row=proof_fixture(tmp_path);assert b.seed(tmp_path,cp)==[row]
    cp['source_cursor']='2019-10-21'
    with pytest.raises(ValueError,match='COMPLETE_COMMITTED_PROOF_AXIS'):b.seed(tmp_path,cp)


@pytest.mark.parametrize('change',['chain','schema','state','watch'])
def test_proof_or_financial_identity_mismatch_refuses(tmp_path,change):
    cp,row=proof_fixture(tmp_path)
    if change in ('chain','schema'):
        row['chain_sha256' if change=='chain' else 'schema']='wrong'
        (tmp_path/'uncertainty-certificate.jsonl').write_bytes(b.encoded(row)+b'\n')
    else:
        name='daily' if change=='state' else 'watch';path=tmp_path/'book'/(name+'.jsonl');v=json.loads(path.read_bytes())
        v['state_sha256' if change=='state' else 'certificate_chain_sha256']='0'*64;raw=b.encoded(v)+b'\n';path.write_bytes(raw)
        cp['journals'][name]=dict(bytes=len(raw),prefix_sha256=b.hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError):b.seed(tmp_path,cp)
