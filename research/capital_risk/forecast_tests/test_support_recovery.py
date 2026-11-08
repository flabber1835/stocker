"""Missing sidecars cannot authorize changing a financial predecessor."""
import ast
import hashlib
import json
from pathlib import Path

import pytest
import system_campaign_support_recovery as module


def fixture(tmp_path):
    current, source, out = (tmp_path/n for n in ('current', 'source', 'out'))
    for root in (current, source, out):root.mkdir()
    for name in module.BOOK:
        for root in (current, source):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
    for name in module.SUPPORT:(source/name).write_bytes(('original '+name).encode())
    spec=dict(arm='P02',selected_checkpoint='book/checkpoint.json.gz',selected_session='2020-02-28',
        outer_sha256='a'*64,inner_sha256='b'*64,state_sha256='c'*64,input_sha256='d'*64,
        base={'parameters':'fixed'},repairs=[],selected_file=module.fingerprint(current/'book/checkpoint.json.gz'),
        journals={'daily':'unchanged'},source_binding_sha256='e'*64,
        run_id=41089567127,artifact_id=12993920969,zip_sha256='f'*64)
    support={**spec,'run_id':41080685843,'artifact_id':12989368853,'zip_sha256':'0'*64,
        'support_files':{n:module.fingerprint(source/n) for n in module.SUPPORT}}
    return current,source,out,spec,support


def test_restores_complete_closure_without_mutating_current_or_financial_files(tmp_path):
    current,source,out,spec,support=fixture(tmp_path)
    before={p.relative_to(current).as_posix():p.read_bytes() for p in current.rglob('*') if p.is_file()}
    view=module.recover_view(current,source,spec,support,out)
    assert {p.relative_to(current).as_posix():p.read_bytes() for p in current.rglob('*') if p.is_file()}==before
    assert set(p.relative_to(view).as_posix() for p in view.rglob('*') if p.is_file())==set(before)|set(module.SUPPORT)
    assert all((view/n).read_bytes()==(source/n).read_bytes()==(out/'lineage/admitted-support'/n).read_bytes() for n in module.SUPPORT)
    proof=json.loads((out/'lineage/admitted-support/recovery.json').read_bytes())
    assert proof['current_run_id']==spec['run_id'] and proof['financial_sessions_advanced']==0
    assert proof['no_financial_checkpoint_selected_from_support'] and proof['all_full_journal_bytes_identical']


@pytest.mark.parametrize('name',module.BOOK)
def test_any_changed_checkpoint_identity_source_or_full_journal_refuses_before_view(tmp_path,name):
    current,source,out,spec,support=fixture(tmp_path)
    (source/name).write_bytes(b'different')
    with pytest.raises(ValueError,match='IDENTICAL_CHECKPOINT_IDENTITY_SOURCE_AND_FULL_JOURNALS'):
        module.recover_view(current,source,spec,support,out)
    assert not (current.parent/'admitted-proof-view').exists()


def test_actual_guard_removal_allows_forbidden_same_prefix_different_tail_graft(tmp_path):
    current,source,out,spec,support=fixture(tmp_path)
    (source/'book/daily.jsonl').write_bytes((current/'book/daily.jsonl').read_bytes()+b'other tail')
    with pytest.raises(ValueError,match='IDENTICAL_CHECKPOINT_IDENTITY_SOURCE_AND_FULL_JOURNALS'):
        module.recover_view(current,source,spec,support,out)
    tree=ast.parse(Path(module.__file__).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='recover_view')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant) and x.value=='SUPPORT_IDENTICAL_CHECKPOINT_IDENTITY_SOURCE_AND_FULL_JOURNALS' for x in ast.walk(n))]
    scope=dict(module.__dict__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-full-journal-guard-removed>','exec'),scope)
    scope[node.name](current,source,spec,support,out)


def test_existing_current_evidence_is_never_replaced(tmp_path):
    current,source,out,spec,support=fixture(tmp_path)
    name=module.SUPPORT[0];(current/name).write_bytes(b'existing actual current result')
    view=module.recover_view(current,source,spec,support,out)
    assert (view/name).read_bytes()==(current/name).read_bytes()!= (source/name).read_bytes()
    proof=json.loads((out/'lineage/admitted-support/recovery.json').read_bytes())
    assert proof['files'][name]['origin']=='CURRENT_BRANCH'


@pytest.mark.parametrize('mode',('missing','changed'))
def test_missing_or_corrupt_support_refuses_before_view(tmp_path,mode):
    current,source,out,spec,support=fixture(tmp_path)
    path=source/module.SUPPORT[-1]
    if mode=='missing':path.unlink()
    else:path.write_bytes(b'corrupt')
    with pytest.raises(ValueError):module.recover_view(current,source,spec,support,out)
    assert not (current.parent/'admitted-proof-view').exists()


def test_complete_current_branch_does_not_fetch_or_replace_support(tmp_path,monkeypatch):
    current,source,out,spec,support=fixture(tmp_path)
    for name in module.SUPPORT:(current/name).write_bytes(b'current evidence')
    import probe,system_campaign_factual_admit
    monkeypatch.setattr(probe,'check_context',lambda _:None)
    def forbidden(*a,**k):raise AssertionError('gratuitous fetch')
    monkeypatch.setattr(system_campaign_factual_admit,'admit',forbidden)
    assert module.hosted_view(current,spec,support,out,tmp_path,b'not-used',limit=1024**3)==current
