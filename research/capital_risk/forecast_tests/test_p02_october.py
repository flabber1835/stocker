"""Own-prefix metadata boundaries; no canonical or financial execution."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import system_campaign_completion_review as reviewer
import system_campaign_p02_october_job as job


HERE = Path(job.__file__).parent


def parent(tmp_path):
    cp = dict(sha256='1' * 64, source_cursor='2022-09-30', completed=1196, repairs=[{}] * 27)
    proof = dict(checkpoint_sha256=cp['sha256'], rows=742, comparisons=1375,
        every_actual_comparison_invariant=True, every_committed_watch_and_financial_row_bound=True,
        every_discrete_controller_state_equal=True, no_owned_cvr_accounting_supported=True,
        event_resolution={'path': 'book/pre-event/original.json.gz'})
    raw = (json.dumps(proof) + '\n').encode()
    (tmp_path / 'uncertainty-certificate-review.json').write_bytes(raw)
    spec = dict(outer_sha256=cp['sha256'], interval_review_sha256=hashlib.sha256(raw).hexdigest())
    return cp, spec, proof


def test_accepts_exact_september_parent_without_replaying_old_events(tmp_path):
    cp, spec, proof = parent(tmp_path)
    raw, actual = reviewer.parent_review(tmp_path, cp, spec)
    assert actual == proof and hashlib.sha256(raw).hexdigest() == spec['interval_review_sha256']


@pytest.mark.parametrize('field,value', [('source_cursor', '2022-10-03'), ('completed', 1197),
                                       ('sha256', '0' * 64), ('repairs', [{}] * 26)])
def test_rejects_unsent_row_or_wrong_parent(tmp_path, field, value):
    cp, spec, _ = parent(tmp_path); cp[field] = value
    with pytest.raises(ValueError, match='EXACT_ACTUAL_SEPTEMBER_PARENT'):
        reviewer.parent_review(tmp_path, cp, spec)


def test_cannot_substitute_old_593_row_review(tmp_path):
    cp, spec, proof = parent(tmp_path); proof['rows'] = 593
    raw = json.dumps(proof).encode(); (tmp_path / 'uncertainty-certificate-review.json').write_bytes(raw)
    spec['interval_review_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match='AUTHENTICATED_TWO_EVENT_PARENT_PROOF'):
        reviewer.parent_review(tmp_path, cp, spec)


def test_parent_guard_removal_falsifier(tmp_path):
    cp, spec, _ = parent(tmp_path); cp['source_cursor'] = '2022-10-03'
    source = ast.parse(Path(reviewer.__file__).read_bytes())
    fn, = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'parent_review']
    guards = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(x, ast.Constant) and x.value == 'COMPLETION_EXACT_ACTUAL_SEPTEMBER_PARENT'
                      for x in n.value.args)]
    assert len(guards) == 1
    fn.body.remove(guards[0]); namespace = dict(vars(reviewer))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<removed-own-parent-guard-falsifier>', 'exec'), namespace)
    with pytest.raises(ValueError): reviewer.parent_review(tmp_path, cp, spec)
    # The same wrong-parent regression would fail if the real guard were absent.
    assert namespace['parent_review'](tmp_path, cp, spec)[1]['rows'] == 742


def test_dispatch_keeps_all_inherited_drivers_and_one_candidate():
    from system_campaign_p02_zogenix_job import SOURCES as previous
    assert set(previous) <= set(job.SOURCES)
    assert len(job.SOURCES) == 165 and len(job.SOURCES) - len(previous) == 9
    predecessor = json.loads((HERE / 'system-campaign-p02-october-predecessor.json').read_bytes())
    assert (predecessor['run_id'], predecessor['selected_session'], predecessor['arm']) == (41151496224, '2022-09-30', 'P02')
    assert predecessor['outer_sha256'] == '1ea1ef30f14b2e3e42a91290adffea64674de374cb3245c5c45ec436c9deb490'
    source = (HERE / 'system_campaign_p02_october_run.py').read_text()
    assert source.count('backtest.main, args') == 1
    assert source.index("timing.call('actual_merged_batch_canonical_gate'") < source.index("timing.call('financial_driver_total'")
    assert "arguments(out / 'book', True)" in source
    assert 'runtime.start(' not in source
