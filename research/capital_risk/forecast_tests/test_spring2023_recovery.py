"""Complete-byte exact recovery guards; synthetic metadata, never a replay."""
import ast
import json
from pathlib import Path

import pytest

import system_campaign_spring2023_recovery as recovery


def fixture(tmp_path, monkeypatch):
    names = ['book/checkpoint.json.gz', 'book/identity.json', 'source-bindings.json',
             *['book/' + n + '.jsonl' for n in ('formation', 'daily', 'monthly', 'watch')]]
    checked = {}
    for name in names:
        data = ('synthetic bytes including unsent tail: ' + name).encode()
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        checked[name] = dict(bytes=len(data), sha256=recovery.sha(data))
    proof = dict(status='EXACT_SAME_FINANCIAL_PARENT_NO_REPLAY_ENTRY', failed_run_id=41178393607,
        failed_head='b1e51f2e78c272e510f38e9f605f78a91fb546fe', failed_artifact_id=13034330753,
        actual_worker_exit_code=1, actual_reviewer_exit_code=0, all_inventory_members_authenticated=7,
        all_driver_git_blobs_verified=189, actual_stopped_fences_verified=True,
        financial_entry_not_reached=True, new_ordinary_overlay_not_created=True, new_input_not_adopted=True,
        financial_parent_run_id=41174261514, financial_parent_outer_sha256='1' * 64,
        financial_parent_session='2023-03-31', measured_closes=1321, retained_input_descriptors=29,
        no_checkpoint_rollback_or_new_origin=True, production_contacted=False,
        exact_unchanged_members=checked)
    driver = tmp_path / 'driver'; driver.mkdir()
    raw = json.dumps(proof).encode(); (driver / recovery.EQUIVALENCE).write_bytes(raw)
    monkeypatch.setattr(recovery, 'HERE', driver)
    spec = dict(run_id=41174261514, outer_sha256='1' * 64, selected_session='2023-03-31',
                selected_file=checked['book/checkpoint.json.gz'])
    request = dict(spring2023_unadvanced_equivalence_sha256=recovery.sha(raw))
    return spec, request


def test_exact_original_parent_and_complete_files_admit(tmp_path, monkeypatch):
    spec, request = fixture(tmp_path, monkeypatch)
    result = recovery.verify(tmp_path, spec, request)
    assert result['financial_parent_run_id'] == 41174261514
    assert result['failed_run_id'] == 41178393607 and len(result['exact_unchanged_members']) == 7


@pytest.mark.parametrize('name', ['book/checkpoint.json.gz', 'book/daily.jsonl', 'book/watch.jsonl'])
def test_changed_checkpoint_or_unsent_tail_refuses(tmp_path, monkeypatch, name):
    spec, request = fixture(tmp_path, monkeypatch)
    with (tmp_path / name).open('ab') as stream: stream.write(b'changed-unsent-byte')
    with pytest.raises(ValueError, match='ALL_UNSENT_TAIL_BYTES'):
        recovery.verify(tmp_path, spec, request)


def test_wrong_proof_or_financial_parent_refuses(tmp_path, monkeypatch):
    spec, request = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='AUTHENTICATED_FAILURE_RECORD'):
        recovery.verify(tmp_path, spec, dict(spring2023_unadvanced_equivalence_sha256='0' * 64))
    spec['run_id'] = 41178393607  # Failed attempt is not the complete financial parent.
    with pytest.raises(ValueError, match='UNADVANCED_OWN_FINANCIAL_AUTHORITY'):
        recovery.verify(tmp_path, spec, request)


def test_actual_complete_tail_guard_removal_falsifier(tmp_path, monkeypatch):
    spec, request = fixture(tmp_path, monkeypatch)
    with (tmp_path / 'book/daily.jsonl').open('ab') as stream: stream.write(b'changed-unsent-byte')
    tree = ast.parse(Path(recovery.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verify']
    loop, = [n for n in fn.body if isinstance(n, ast.For)]
    guard, = [n for n in loop.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'SPRING2023_RECOVERY_ACTUAL_COMPLETE_PARENT_AND_ALL_UNSENT_TAIL_BYTES'
                      for a in n.value.args)]
    loop.body.remove(guard)
    namespace = dict(vars(recovery))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-complete-tail-guard-removed>', 'exec'), namespace)
    with pytest.raises(ValueError): recovery.verify(tmp_path, spec, request)
    assert namespace['verify'](tmp_path, spec, request)['no_checkpoint_rollback_or_new_origin']
