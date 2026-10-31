"""Synthetic immutable checkpoint naming and identity-resolution regressions."""
import gzip
import json
from pathlib import Path

import pytest

from system_campaign_facts import digest
from system_campaign_uncertainty_archive import EvidenceRoot, REQUESTED, resolve


def fixture(root):
    directory=root/'book/pre-event';directory.mkdir(parents=True)
    cp=dict(source_cursor='2019-10-21',run=dict(state_sha256='a'*64,input_sha256='b'*64))
    cp['sha256']=digest(cp)
    actual=directory/('2019-10-22-'+cp['sha256']+'.json.gz')
    raw=gzip.compress(json.dumps(cp).encode(),mtime=0);actual.write_bytes(raw)
    record=dict(session='2019-10-22',prior_state_sha256='a'*64,input_sha256='b'*64)
    (root/'uncertainty-certificate.jsonl').write_text(json.dumps(record)+'\n')
    return actual,cp,raw


def test_real_producer_name_resolves_without_alias_or_relabel(tmp_path):
    actual,cp,raw=fixture(tmp_path)
    resolved,proof=resolve(tmp_path)
    assert resolved==actual and proof['outer_sha256']==cp['sha256']
    view=EvidenceRoot(tmp_path,actual)
    assert view/REQUESTED==actual and view/'book/checkpoint.json.gz'==tmp_path/'book/checkpoint.json.gz'
    assert actual.read_bytes()==raw and not (tmp_path/REQUESTED).exists()
    assert not proof['new_checkpoint_or_alias_created'] and not proof['checkpoint_bytes_or_name_changed']


@pytest.mark.parametrize('field',['prior_state_sha256','input_sha256'])
def test_different_predecessor_identity_cannot_be_used(tmp_path,field):
    fixture(tmp_path)
    path=tmp_path/'uncertainty-certificate.jsonl';v=json.loads(path.read_text());v[field]='c'*64;path.write_text(json.dumps(v)+'\n')
    with pytest.raises(ValueError,match='UNIQUE_EXACT_PRE_EVENT'):resolve(tmp_path)


def test_forged_archive_filename_or_outer_digest_refuses(tmp_path):
    actual,_,_=fixture(tmp_path)
    actual.rename(actual.with_name('2019-10-22-'+'f'*64+'.json.gz'))
    with pytest.raises(ValueError,match='CANONICAL_PRODUCER_NAME'):resolve(tmp_path)


def test_actual_state_identity_guard_removal_falsifier(tmp_path):
    import inspect,textwrap
    from system_campaign_uncertainty_archive import resolve as function
    fixture(tmp_path)
    path=tmp_path/'uncertainty-certificate.jsonl';v=json.loads(path.read_text());v['prior_state_sha256']='c'*64;path.write_text(json.dumps(v)+'\n')
    with pytest.raises(ValueError,match='UNIQUE_EXACT_PRE_EVENT'):function(tmp_path)
    raw=inspect.getsource(function)
    broken=raw.replace("and cp['run']['state_sha256']==first['prior_state_sha256']",'and True')
    assert broken!=raw
    namespace={};exec(textwrap.dedent(broken),function.__globals__,namespace)
    assert namespace['resolve'](tmp_path)[1]['outer_sha256']
