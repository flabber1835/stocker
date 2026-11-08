"""Synthetic own-origin evidence; no canonical financial transition is executed."""
import ast,gzip,hashlib,json
from pathlib import Path
import pytest
from system_campaign_own_origin import capture,qualify


def prepared(tmp_path,monkeypatch):
    import probe
    monkeypatch.setattr(probe,'check_context',lambda environment:None)
    ref=tmp_path/'reference';old=tmp_path/'old';out=tmp_path/'out'
    for root in (ref,old,out):root.mkdir()
    for root in (ref,old):
        (root/'book').mkdir();(root/'book/identity.json').write_bytes(b'OWN-SYNTHETIC-BOOK');(root/'source-bindings.json').write_bytes(b'SAME-SYNTHETIC-SOURCE')
    cp={'sha256':'a'*64,'source_cursor':'2017-06-30','completed':0,'base':{'synthetic':'source'},
        'run':{'state_sha256':'b'*64,'state':{'last_processed_session':None}},
        'journals':{n:{'bytes':0,'prefix_sha256':hashlib.sha256(b'').hexdigest()} for n in ('formation','daily','monthly','watch')}}
    raw=gzip.compress(json.dumps(cp).encode());(ref/('a'*64+'.json.gz')).write_bytes(raw)
    admission={'schema':'research.full-system-own-origin/1','outer_sha256':'a'*64,'state_sha256':'b'*64,'outer_file_sha256':hashlib.sha256(raw).hexdigest(),
        'resume_session':'2017-06-30','canonical_roundtrip':True,'all_four_prefixes_empty_verified':True}
    (ref/'origin-admission.json').write_text(json.dumps(admission));(old/'book/checkpoint.json.gz').write_bytes(raw)
    return ref,old,out,raw


def test_own_origin_retained_byte_exact_but_never_resume(tmp_path,monkeypatch):
    ref,old,out,raw=prepared(tmp_path,monkeypatch);before=(old/'book/checkpoint.json.gz').read_bytes();capture(ref,old,out)
    retained=out/'lineage/original-own-origin'
    assert (retained/('a'*64+'.json.gz')).read_bytes()==raw
    assert (old/'book/checkpoint.json.gz').read_bytes()==before and not (out/'book').exists()
    assert json.loads((retained/'preservation.json').read_bytes())['financial_resume_checkpoint_unchanged']


def test_cross_book_refusal_and_actual_guard_removal(tmp_path,monkeypatch):
    ref,old,out,raw=prepared(tmp_path,monkeypatch);(old/'book/identity.json').write_bytes(b'OTHER-SYNTHETIC-BOOK')
    with pytest.raises(ValueError,match='EXACT_SAME_SOURCE_AND_BOOK'):capture(ref,old,out)
    node=next(n for n in ast.parse(Path(capture.__code__.co_filename).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='capture')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant) and x.value=='OWN_ORIGIN_EXACT_SAME_SOURCE_AND_BOOK' for x in ast.walk(n))]
    scope=dict(capture.__globals__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-own-book-guard>','exec'),scope)
    scope['capture'](ref,old,out)
    assert (out/'lineage/original-own-origin/origin-admission.json').is_file()


def test_no_local_canonical_origin_restore(monkeypatch,tmp_path):
    monkeypatch.delenv('FULL_SYSTEM_HOSTED',raising=False)
    with pytest.raises(ValueError,match='HOSTED'):qualify(Path('/absent'),{},tmp_path/'absent')
    assert not (tmp_path/'absent').exists()
