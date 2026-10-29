"""Finite transfer limits and exact opaque-ancestor preservation."""
import ast,hashlib
from pathlib import Path
import pytest
from system_campaign_factual_admit import archive_bound
from system_campaign_ancestor import preserve


def test_explicit_archive_capacity_and_actual_limit_guard_removal():
    archive_bound({'zip_bytes':300*1024**2},512*1024**2)
    with pytest.raises(ValueError,match='DOWNLOAD_BOUND'):archive_bound({'zip_bytes':300*1024**2},256*1024**2)
    with pytest.raises(ValueError,match='DECLARED_ARCHIVE_LIMIT'):archive_bound({'zip_bytes':1},1024**3)
    node=next(n for n in ast.parse(Path(archive_bound.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='archive_bound')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant)
        and x.value=='FACTUAL_DECLARED_ARCHIVE_LIMIT' for x in ast.walk(n))]
    scope=dict(archive_bound.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-archive-cap>','exec'),scope)
    scope['archive_bound']({'zip_bytes':1},1024**3)


def test_exact_ancestor_bytes_and_actual_copy_guard_removal(tmp_path,monkeypatch):
    old=tmp_path/'transfer/branch';old.mkdir(parents=True);raw=b'SYNTHETIC-OPAQUE-CIPHER';source=old.parent/'predecessor.zip';source.write_bytes(raw)
    spec={'artifact_id':1,'run_id':2,'head':'fake','zip_bytes':len(raw),'zip_sha256':hashlib.sha256(raw).hexdigest()}
    out=tmp_path/'clean';out.mkdir();assert preserve(old,out,spec)['zip_sha256']==spec['zip_sha256']
    import system_campaign_ancestor as module
    original=module.shutil.copyfile
    def corrupt(a,b):original(a,b);Path(b).write_bytes(b'corrupted')
    monkeypatch.setattr(module.shutil,'copyfile',corrupt)
    failed=tmp_path/'failed';failed.mkdir()
    with pytest.raises(ValueError,match='EXACT_PRESERVED_ZIP'):preserve(old,failed,spec)
    node=next(n for n in ast.parse(Path(preserve.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='preserve')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant)
        and x.value=='ANCESTOR_EXACT_PRESERVED_ZIP' for x in ast.walk(n))]
    scope=dict(preserve.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<removed-ancestor-copy-sha>','exec'),scope)
    unsafe=tmp_path/'unsafe';unsafe.mkdir();scope['preserve'](old,unsafe,spec)
    assert (unsafe/'lineage/verified-ancestor.zip').read_bytes()!=raw and source.read_bytes()==raw
