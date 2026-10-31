"""Exact orchestration metadata and inert export/tail checks; no hosted calls."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest
import system_campaign_pxd_qualification_job as job
import system_campaign_pxd_qualification_run as entry


def test_exact_new_request_retains_every_old_source_and_disallows_financial_mode():
    request=job.expected_request()
    assert len(request['sources'])==277 and len(set(job.SOURCES))==277
    assert set(request['sources'])==set(job.SOURCES)
    assert request['financial_replay_authorized'] is False
    assert request['financial_resume_from_qualification_copy_authorized'] is False
    assert request['full_local_financial_admission_required_before_financial_resume'] is True
    assert request['qualification_wait_seconds']==900
    old=job.inherited_request()
    assert {k:request['sources'][k] for k in old['sources']}==old['sources']
    raw=(job.HERE.parents[1]/'.github/workflows/capital-system-p02-pxd-qualification.yml').read_text()
    assert 'retention-days: 7' in raw and 'group: system-optimization-002-p02-only' in raw
    assert 'cancel-in-progress: false' in raw and 'workflow_dispatch' not in raw
    assert 'timeout-minutes: 60' in raw and 'capital-system-p02-pxd-qualification' not in request['sources']


def test_only_exact_zero_session_private_entrypoint(monkeypatch):
    command=['-B','-u','/driver/system_campaign_pxd_qualification_run.py',
        '--request','/driver/system-campaign-pxd-qualification-request.json']
    fake={'Config':{'Cmd':command}}
    monkeypatch.setattr(job,'prior_inspect',lambda name,identity:deepcopy(fake))
    assert job.inspect('inert',None)==fake
    fake['Config']['Cmd'][2]='/driver/system_campaign_p02_close_run.py'
    with pytest.raises(ValueError,match='ONLY_ZERO_SESSION_ENTRYPOINT'):job.inspect('inert',None)


def test_export_does_not_include_disposable_book_or_unbounded_data(tmp_path):
    (tmp_path/'request.json').write_bytes(b'{}')
    job.export_bound(tmp_path,100)
    with pytest.raises(ValueError):job.export_bound(tmp_path,1)
    (tmp_path/'work').mkdir();(tmp_path/'work/daily.jsonl').write_bytes(b'inert unwanted copy')
    with pytest.raises(ValueError,match='COMPACT_PROOF_ONLY'):job.export_bound(tmp_path,100)
    node,=[n for n in ast.parse(Path(job.__file__).read_bytes()).body
           if isinstance(n,ast.FunctionDef) and n.name=='export_bound']
    node.body=[n for n in node.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and isinstance(n.value.func,ast.Name) and n.value.func.id=='need')]
    namespace=dict(vars(job))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<actual-proof-only-export-guard-removed>','exec'),namespace)
    namespace['export_bound'](tmp_path,100)


def journals(tmp_path):
    before,after=tmp_path/'original',tmp_path/'candidate';before.mkdir();after.mkdir()
    cp={'journals':{}};current={'journals':{}};event={'inert_input_event':True}
    for name in ('daily','formation','watch','monthly'):
        prefix=b'{"inert":1}\n';tail=b'{"unsent_inert":2}\n' if name=='daily' else b''
        (before/(name+'.jsonl')).write_bytes(prefix+tail)
        value=prefix+((json.dumps(event)+'\n').encode() if name=='watch' else b'')
        (after/(name+'.jsonl')).write_bytes(value)
        cp['journals'][name]={'bytes':len(prefix),'prefix_sha256':job.sha256_file(before/(name+'.jsonl')) if not tail else __import__('hashlib').sha256(prefix).hexdigest()}
        current['journals'][name]={'bytes':len(value),'prefix_sha256':__import__('hashlib').sha256(value).hexdigest()}
        if tail:(after/'interrupted-daily-inert.jsonl').write_bytes(tail)
    return before,after,cp,current,event


def test_actual_prefix_and_tail_metadata_checked_without_replay(tmp_path):
    before,after,cp,current,event=journals(tmp_path)
    proof=entry.prefixes_and_tails(before,after,cp,current,event)
    assert proof['checks']['daily']['tail_bytes']>0


@pytest.mark.parametrize('change',['lost_tail','changed_prefix','financial_row','extra_watch','old_archive'])
def test_no_loss_truncation_or_uncommitted_suffix_reuse(tmp_path,change):
    before,after,cp,current,event=journals(tmp_path)
    if change=='lost_tail':(after/'interrupted-daily-inert.jsonl').unlink()
    elif change=='changed_prefix':(after/'monthly.jsonl').write_bytes(b'changed')
    elif change=='financial_row':
        with (after/'daily.jsonl').open('ab') as stream:stream.write(b'{"new_inert_row":3}\n')
    elif change=='extra_watch':
        with (after/'watch.jsonl').open('ab') as stream:stream.write(b'{"extra_inert_event":3}\n')
    else:(before/'interrupted-daily-inert.jsonl').write_bytes((after/'interrupted-daily-inert.jsonl').read_bytes())
    with pytest.raises(ValueError):entry.prefixes_and_tails(before,after,cp,current,event)
