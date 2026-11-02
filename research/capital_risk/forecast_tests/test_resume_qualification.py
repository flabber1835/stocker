"""Stopped byte-comparator and static hosted-boundary checks; no replay."""
from copy import deepcopy
import ast,gzip,inspect,json
from pathlib import Path
import pytest
import system_campaign_resume_qualification as q


def checkpoint():
    return dict(sha256='outer',source_cursor='2021-09-01',completed=924,base={'source':'immutable'},
        repairs=[{'input':'unchanged'}],journals={'daily':dict(bytes=4)},
        run=dict(checkpoint_sha256='inner',state_sha256='state',input_sha256='input',state={'cash':'123.4'}),chain='chain')


def root(path,cp):
    (path/'book').mkdir(parents=True);(path/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
    (path/'book/daily.jsonl').write_bytes(b'row\n')
    (path/'correlation-inputs.jsonl.gz').write_bytes(gzip.compress(b'correlation\n'))
    (path/'uncertainty-certificate.jsonl').write_bytes(b'certificate\n');return path


def test_exact_checkpoint_and_committed_streams_are_compared(tmp_path):
    cp=checkpoint();a=root(tmp_path/'a',cp);b=root(tmp_path/'b',cp)
    assert q.compare_books(a,b)['all_next_checkpoint_fields_and_journal_bytes_equal']


@pytest.mark.parametrize('kind',('cash','chain','source','input','cursor','repair','journal','capture','certificate','tail'))
def test_economic_identity_or_evidence_mutation_refuses(tmp_path,kind):
    cp=checkpoint();wrong=deepcopy(cp)
    if kind=='cash':wrong['run']['state']['cash']='123.5'
    if kind=='chain':wrong['chain']='different'
    if kind=='source':wrong['base']['source']='different'
    if kind=='input':wrong['run']['input_sha256']='different'
    if kind=='cursor':wrong['source_cursor']='2021-09-02'
    if kind=='repair':wrong['repairs'][0]['input']='different'
    a=root(tmp_path/'a',cp);b=root(tmp_path/'b',wrong)
    if kind=='journal':(b/'book/daily.jsonl').write_bytes(b'bad\n')
    if kind=='capture':(b/'correlation-inputs.jsonl.gz').write_bytes(gzip.compress(b'different\n'))
    if kind=='certificate':(b/'uncertainty-certificate.jsonl').write_bytes(b'different\n')
    if kind=='tail':(b/'book/daily.jsonl').write_bytes(b'row\nunsent\n')
    with pytest.raises(ValueError):q.compare_books(a,b)


def spec(cp):
    return dict(outer_sha256=cp['sha256'],selected_session=cp['source_cursor'],base=cp['base'],repairs=cp['repairs'],
        journals=cp['journals'],inner_sha256=cp['run']['checkpoint_sha256'],state_sha256=cp['run']['state_sha256'],input_sha256=cp['run']['input_sha256'])


def test_actual_predecessor_guard_removal_falsifier():
    cp=checkpoint();selected=spec(cp);q.require_predecessor(cp,selected);selected['outer_sha256']='wrong'
    with pytest.raises(ValueError):q.require_predecessor(cp,selected)
    tree=ast.parse(inspect.getsource(q.require_predecessor));tree.body[0].body=[ast.Pass()]
    scope=dict(vars(q));exec(compile(ast.fix_missing_locations(tree),'<pure-predecessor-guard-removed>','exec'),scope)
    scope['require_predecessor'](cp,selected)


def test_all_canonical_probe_operations_refuse_locally():
    for fn in (lambda:q.probe(None,None,None,None,'COLD'),lambda:q.qualify(None,None,None,None),
               lambda:q.falsify(None),lambda:q.Capture('x','y').__enter__()):
        with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):fn()


def test_two_sequential_full_journal_probes_never_select_a_new_predecessor():
    text=Path(q.__file__).read_text();ast.parse(text)
    assert "for mode in ('COLD','BOUNDED'):" in text
    assert "maximum=1" in text and "current['repairs']==cp['repairs']" in text
    assert 'qualification_only_not_economic_predecessor=True' in text and 'selected_for_economic_use=False' in text


def test_job_request_closure_and_exact_latest_own_checkpoint():
    import system_campaign_reconstruction_job as job
    from forecast_tests.test_basis_job_sources import dependencies
    assert not dependencies(job.SOURCES)-set(job.SOURCES)
    request=job.expected_request()
    assert request['economic_suffix_started'] is False and request['new_origin'] is False
    assert request['new_overlay'] is False and request['probe_next_session']=='2021-12-01'
    assert request['probe_modes']==['COLD','BOUNDED'] and request['probe_measured_transitions_each']==1
    assert request['qualification_wait_seconds']==1200 and request['artifact_retention_days']==7
    assert json.loads((job.HERE/'system-campaign-reconstruction-request.json').read_bytes())==request


def test_qualification_workflow_is_isolated_and_request_triggered():
    path=Path(__file__).resolve().parents[3]/'.github/workflows/capital-system-reconstruction-qualification.yml'
    text=path.read_text()
    assert 'branches: [codex/capital-risk-research]' in text
    assert "paths: ['research/capital_risk/system-campaign-reconstruction-request.json']" in text
    assert 'system-optimization-002-p02-only' in text and 'cancel-in-progress: false' in text
    assert 'timeout-minutes: 45' in text and 'retention-days: 7' in text
    assert 'system_campaign_reconstruction_job.py' in text and 'environment: production' not in text
