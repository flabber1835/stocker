"""Collision and observation guards; no canonical or financial execution."""
import ast
from copy import deepcopy
import inspect,json
from pathlib import Path
import pytest
import system_campaign_action_preflight as action
from system_campaign_phase_timing import PhaseTiming


def fixture(tmp_path):
    catalog=json.loads((Path(__file__).parents[1]/'system-campaign-following-completions-terminal-facts.json').read_bytes())
    a=deepcopy(catalog['terms'][1]);a['added']['cash_in_lieu_price_per_delivered_share']=0.
    doc=dict(schema='terminal-repair/1',suppress=[dict(session=a['native_session'],security_id=a['security_id'],term_sha256=a['native_term_sha256'])],add=[a['added']])
    raw=json.dumps(doc).encode();h=action.sha(raw);d=tmp_path/'book/repairs';d.mkdir(parents=True);(d/(h+'.json')).write_bytes(raw)
    cp=dict(sha256='a'*64,source_cursor='2021-01-29',run=dict(input_sha256='b'*64),repairs=[dict(filename=h+'.json',sha256=h)])
    return cp,catalog


def test_actual_failed_public_batch_is_refused_by_prior_keys(tmp_path):
    cp,catalog=fixture(tmp_path);r=action.analyze_new_catalog(cp,tmp_path,catalog)
    assert [v['reason'] for v in r['conflicts']]==['RETAINED_SUPPRESSION_KEY_ALREADY_PRESENT','RETAINED_ADDITION_KEY_ALREADY_PRESENT']
    assert all(v['ticker']=='APHA' for v in r['conflicts'])
    with pytest.raises(ValueError,match='DISJOINT_UNCONSUMED'):action.require_disjoint(r)
    # Remove the actual admission guard and this bad report becomes accepted.
    node=ast.parse(inspect.getsource(action.require_disjoint)).body[0];node.body=[ast.Pass()]
    scope={};exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<guard-removed>','exec'),scope)
    scope['require_disjoint'](r)


def test_disjoint_events_pass_without_silent_changes(tmp_path):
    cp,c=fixture(tmp_path);c['terms']=[v for v in c['terms'] if v['ticker']!='APHA'];before=deepcopy(c)
    r=action.analyze_new_catalog(cp,tmp_path,c);action.require_disjoint(r);assert c==before
    assert r['requested_events']==5


@pytest.mark.parametrize('kind',('consumed','internal','corrupt','filename','identity'))
def test_refuses_consumed_duplicate_corrupt_or_rebound_input(tmp_path,kind):
    cp,c=fixture(tmp_path);c['terms']=[c['terms'][0]]
    if kind=='consumed':cp['source_cursor']='2021-02-26'
    elif kind=='internal':c['terms']*=2
    elif kind=='corrupt':(tmp_path/'book/repairs'/cp['repairs'][0]['filename']).write_bytes(b'{}')
    elif kind=='filename':cp['repairs'][0]['filename']='wrong.json'
    else:c['terms'][0]['added']['security_id']='WRONG'
    with pytest.raises(ValueError):action.require_disjoint(action.analyze_new_catalog(cp,tmp_path,c))


def test_phase_observation_preserves_exact_return_and_original_exception(tmp_path):
    result=object();error=ValueError('original')
    with pytest.raises(ValueError) as caught:
        with PhaseTiming(tmp_path,'synthetic') as timing:
            assert timing.call('identity',lambda:result) is result
            with timing.phase('failure'):raise error
    assert caught.value is error
    proof=json.loads((tmp_path/'phase-timing.json').read_bytes())
    assert [(v['name'],v['status']) for v in proof['phases']]==[('identity','PASSED'),('failure','FAILED')]
    assert proof['exceptions_swallowed'] is False and not proof['financial_state_read_or_changed']


def test_timing_export_failure_never_masks_primary_exception(tmp_path,monkeypatch):
    import system_campaign_phase_timing as module
    def fail(*a):raise OSError('export')
    monkeypatch.setattr(module,'save',fail);error=ValueError('original')
    with pytest.raises(ValueError) as caught:
        with PhaseTiming(tmp_path,'synthetic'):raise error
    assert caught.value is error and error.__notes__==['Phase timing export failed: OSError']


def test_packet_timing_preserves_objects_errors_and_generator_close():
    from system_campaign_replay_timing import timed_items
    item=object();error=ValueError('source');events=[];observed=[]
    def source():
        try:
            yield item
            raise error
        finally:events.append('closed')
    stream=timed_items(source(),lambda *v:observed.append(v))
    assert next(stream) is item
    with pytest.raises(ValueError) as caught:next(stream)
    assert caught.value is error and events==['closed']
    assert [(v[1],v[2]) for v in observed]==[(True,False),(False,True)]
