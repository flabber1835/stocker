"""The analytical source fork refuses changed rules and unreviewed revisions."""
import hashlib
import json
import sys

import pytest

from research.economic_replay60 import fork_430

NEW = 'ee23c894c97a2c4023654ce3a56a62728f5b061e'
OLD = 'da7b64a9429c9c73fb7efac90c8d4a5decb39e13'
EXPECTED = ('sentinel/core/kernel.py', 'sentinel/core/spinoffs.py',
            'shared/stock_strategy_shared/wealth_core/ledger.py')
CONTROLLER = 'sentinel/controller/champion_frozen.py'


class ReachedVerifiedBoundary(Exception):
    pass


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    old, new, output = (tmp_path / n for n in ('old', 'new', 'output'))
    files = {}
    for name in (*EXPECTED, CONTROLLER):
        for root in (old, new):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'old' if root == old or name == CONTROLLER else b'new')
        files[name] = hashlib.sha256(b'old').hexdigest()
    for root in (old, new):
        path = root / 'research/bounded_20y/production-source.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(revision=OLD, files=files)))
    monkeypatch.setattr(sys, 'argv', ['fork', '--runtime', str(new),
        '--old-runtime', str(old), '--old-pointer', str(tmp_path/'pointer.json'),
        '--output', str(output), '--revision', NEW])
    def stop_before_import(*_):
        raise ReachedVerifiedBoundary()
    monkeypatch.setattr(fork_430, 'dump', stop_before_import)
    return old, new, output


def test_exact_reviewed_source_delta_reaches_next_boundary(prepared):
    with pytest.raises(ReachedVerifiedBoundary):
        fork_430.main()


def test_modified_controller_source_refuses(prepared):
    _, new, _ = prepared
    (new/CONTROLLER).write_bytes(b'changed controller parameters')
    with pytest.raises(ValueError, match='unexpected production source changes'):
        fork_430.main()


def test_unreviewed_revision_refuses(prepared, monkeypatch):
    monkeypatch.setattr(sys, 'argv', sys.argv[:-1]+['unreviewed'])
    with pytest.raises(ValueError, match='reviewed PR430 revision'):
        fork_430.main()


def test_existing_output_is_preserved(prepared):
    _, _, output = prepared
    output.mkdir()
    marker = output/'keep'
    marker.write_text('prior evidence')
    with pytest.raises(ValueError, match='output already exists'):
        fork_430.main()
    assert marker.read_text() == 'prior evidence'


def test_changed_predecessor_bytes_refuse(prepared):
    old, _, _ = prepared
    (old/CONTROLLER).write_bytes(b'changed predecessor')
    with pytest.raises(ValueError, match='predecessor source changed'):
        fork_430.main()
