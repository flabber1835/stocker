"""Filesystem metadata fixtures only; never a canonical checkpoint or book."""
import ast,os,shutil,stat
from pathlib import Path
import pytest
import system_campaign_p03_thor_runtime as runtime
def metadata_tree(tmp_path,*,owned_name='p03-thor-owned-seed-view-explicit-fixture'):
    output=tmp_path/'output';output.mkdir();owned=output/owned_name;owned.mkdir()
    source=tmp_path/'explicitly-noncanonical-source-metadata';(source/'book').mkdir(parents=True)
    (source/'book/watch.jsonl').write_text('{"explicitly_noncanonical_permission_fixture":true}\n')
    (source/'opaque-metadata.txt').write_text('No financial state, journal or checkpoint.')
    (source/'book/watch.jsonl').chmod(0o444);(source/'opaque-metadata.txt').chmod(0o444)
    (source/'book').chmod(0o555);source.chmod(0o555)
    view=owned/'view';shutil.copytree(source,view)
    return output,owned,view,source
def modes(root):return {str(p.relative_to(root)):stat.S_IMODE(p.stat().st_mode) for p in [root,*root.rglob('*')]}
def test_only_owned_copy_directories_and_named_watch_get_owner_permissions(tmp_path):
    output,owned,view,source=metadata_tree(tmp_path);before=modes(source);selected=(view/'opaque-metadata.txt').read_bytes()
    proof=runtime.owned_view_permissions(view,owned,output)
    assert proof['owned_directories']==2 and proof['original_source_permissions_changed'] is False
    assert all(stat.S_IMODE(p.stat().st_mode)&stat.S_IWUSR for p in (view,view/'book',view/'book/watch.jsonl'))
    assert not stat.S_IMODE((view/'opaque-metadata.txt').stat().st_mode)&stat.S_IWUSR
    assert (view/'opaque-metadata.txt').read_bytes()==selected and modes(source)==before
    (view/'new-explicitly-noncanonical-metadata.txt').write_text('owned copy only')
    (view/'book/watch.jsonl').write_text('explicitly noncanonical replacement marker')
    assert (source/'book/watch.jsonl').read_text()=='{"explicitly_noncanonical_permission_fixture":true}\n'
@pytest.mark.parametrize('change',['owner_name','wrong_owner','wrong_output','missing_watch'])
def test_bad_target_refuses_before_any_permission_change(tmp_path,monkeypatch,change):
    output,owned,view,source=metadata_tree(tmp_path,owned_name='wrong-name' if change=='owner_name' else 'p03-thor-owned-seed-view-explicit-fixture')
    if change=='wrong_owner':owned=output
    elif change=='wrong_output':output=tmp_path
    elif change=='missing_watch':
        (view/'book').chmod(0o700);(view/'book/watch.jsonl').chmod(0o600)
        (view/'book/watch.jsonl').unlink()
    calls=[];monkeypatch.setattr(Path,'chmod',lambda *a,**k:calls.append(a))
    with pytest.raises(ValueError):runtime.owned_view_permissions(view,owned,output)
    assert calls==[]
def test_outer_owned_target_guard_removal_is_meaningful(tmp_path,monkeypatch):
    output,owned,view,source=metadata_tree(tmp_path,owned_name='wrong-name');calls=[]
    monkeypatch.setattr(Path,'chmod',lambda *a,**k:calls.append(a))
    with pytest.raises(ValueError,match='ONLY_EXPLICIT_OWNED_OUTPUT_VIEW'):runtime.owned_view_permissions(view,owned,output)
    fn=next(n for n in ast.parse(Path(runtime.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='owned_view_permissions')
    guards=[n for n in fn.body if isinstance(n,ast.Expr) and 'THOR_RUNTIME_PERMISSION_TARGET_ONLY_EXPLICIT_OWNED_OUTPUT_VIEW' in ast.unparse(n)]
    assert len(guards)==1;fn.body.remove(guards[0]);scope=dict(vars(runtime))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-owned-permission-target-guard>','exec'),scope)
    assert scope['owned_view_permissions'](view,owned,output)['owned_directories']==2 and len(calls)==3
def test_symlink_refuses_before_any_permission_change(tmp_path,monkeypatch):
    output,owned,view,source=metadata_tree(tmp_path)
    view.chmod(0o700)
    try:(view/'outside-link').symlink_to(source,target_is_directory=True)
    except OSError:pytest.skip('This Windows account cannot create symlinks; target/path refusal tests still run.')
    view.chmod(0o555)
    calls=[];monkeypatch.setattr(Path,'chmod',lambda *a,**k:calls.append(a))
    with pytest.raises(ValueError,match='NO_SYMLINKS'):runtime.owned_view_permissions(view,owned,output)
    assert calls==[]
