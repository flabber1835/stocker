"""Candidate review refuses changed identities before reading trial actions."""
from decimal import Decimal
import inspect
import json

import numpy as np
import pytest

from research import structured_search_review as review


def context(tmp_path,monkeypatch,corruption):
    snapshot=tmp_path/'snapshot'; root=tmp_path/'result'
    snapshot.mkdir(); root.mkdir()
    config=dict(source_manifest=dict(binding='original'))
    protocol=json.dumps(config)
    (root/'protocol.json').write_text(protocol)
    summary=dict(protocol_sha256=review.inputs.sha(protocol.encode()))
    if corruption=='protocol': summary['protocol_sha256']='wrong'
    (root/'summary.json').write_text(json.dumps(summary))
    (root/'selections.json').write_text('[]')
    (snapshot/'manifest.json').write_text(json.dumps(dict(binding='wrong' if corruption=='snapshot' else 'original')))
    monkeypatch.setattr(review.inputs,'load',lambda p:(None,[dict(session='2020-01-01')]))
    monkeypatch.setattr(review.accounting,'tape',lambda *a,**kw:([],Decimal(1),[]))
    monkeypatch.setattr(review.data,'matrices',lambda *a:np.zeros((0,3,3)))
    def archive_should_never_run(path):
        raise RuntimeError('unsafe archive reached')
    monkeypatch.setattr(review.audit,'archive',archive_should_never_run)
    return snapshot,root


@pytest.mark.parametrize('corruption',['protocol','snapshot'])
def test_invalid_review_context_refuses_before_reading_actions(tmp_path,monkeypatch,corruption):
    args=context(tmp_path,monkeypatch,corruption)
    expected='protocol identity changed' if corruption=='protocol' else 'different source snapshot'
    with pytest.raises(ValueError,match=expected): review.review(*args)


@pytest.mark.parametrize('corruption',['protocol','snapshot'])
def test_removed_review_identity_guard_fails_its_falsifier(tmp_path,monkeypatch,corruption):
    source=inspect.getsource(review)
    old="if inputs.sha((root/'protocol.json')" if corruption=='protocol' else "if json.loads((snapshot/'manifest.json')"
    assert source.count(old)==1
    source=source.replace(old,old.replace('if ','if False and ',1))
    namespace=dict(__name__='mutated_review',__file__=review.__file__)
    exec(compile(source,review.__file__,'exec'),namespace)
    monkeypatch.setattr(review,'review',namespace['review'])
    with pytest.raises(RuntimeError,match='unsafe archive reached'):
        test_invalid_review_context_refuses_before_reading_actions(tmp_path,monkeypatch,corruption)
