import gzip
import importlib.util
import json
from pathlib import Path
import sys
import pytest

CAP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CAP))
spec=importlib.util.spec_from_file_location('successor',CAP/'p01_iac_namespace_continue.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def synthetic(tmp_path):
    root=tmp_path/'parent';book=root/'book';book.mkdir(parents=True)
    empty=module.sha(b'')
    cp={'completed':879,'source_cursor':'2021-06-29','base':{},'repairs':[{}]*13,
        'run':{'checkpoint_sha256':'a'*64,'state_sha256':'b'*64,'input_sha256':'c'*64},
        'journals':{'daily':{'bytes':0,'prefix_sha256':empty}}}
    cp['sha256']=module.digest(cp)
    raw=gzip.compress(module.encoded(cp));(book/'checkpoint.json.gz').write_bytes(raw)
    (book/'daily.jsonl').write_bytes(b'old-refusal-tail\n')
    spec={'selected_file':{'bytes':len(raw),'sha256':module.sha(raw)},'outer_sha256':cp['sha256'],
          'inner_sha256':'a'*64,'state_sha256':'b'*64,'input_sha256':'c'*64,'base':{},'repairs':cp['repairs'],
          'completed':879,'selected_session':'2021-06-29',
          'tails':{'daily':{'bytes':17,'sha256':module.sha(b'old-refusal-tail\n')}}}
    return root,cp,spec


def test_next_admitted_checkpoint_is_selected_without_replaying_697(tmp_path):
    root,cp,spec=synthetic(tmp_path)
    assert module.parent_check(root,spec)==cp


@pytest.mark.parametrize('field,value',[('completed',880),('selected_session','2021-06-30'),('outer_sha256','d'*64)])
def test_wrong_checkpoint_identity_refuses(tmp_path,field,value):
    root,cp,spec=synthetic(tmp_path);spec[field]=value
    with pytest.raises(ValueError):module.parent_check(root,spec)


def test_refusal_tail_cannot_be_erased_or_admitted(tmp_path):
    root,cp,spec=synthetic(tmp_path);(root/'book/daily.jsonl').write_bytes(b'')
    with pytest.raises(ValueError,match='OLD_TAIL'):module.parent_check(root,spec)
