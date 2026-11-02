"""Real source-bound gate with synthetic anchors; no canonical replay."""
import ast
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_anchor_proofs as module
import system_campaign_parallel_discovery_run as old


def case(tmp_path):
    class Temporal(ValueError): pass
    state = SimpleNamespace(last_processed_session='2020-01-31', state_hash='1'*64, data_version=1,
        feed=dict(series={'SYNTHETIC': dict(signal_basis_anchor=['2018-01-02', 12.5, 13.])}),
        to_dict=lambda: dict(state='SYNTHETIC_UNCHANGED'))
    cache = old.anchor_source.RetainedAnchors(tmp_path, state, source_sha256='1'*64, input_sha256='3'*64)
    cache.stream = (tmp_path/'anchors.jsonl').open('xb')
    cache.m = SimpleNamespace(adapter=SimpleNamespace(protected=lambda v: {'SYNTHETIC'}, TemporalViolation=Temporal),
        VendorBar=lambda day, sid, ticker, raw, *a, signal_close: SimpleNamespace(session=day,
            security_id=sid, ticker=ticker, raw_close=raw, signal_close=signal_close))
    cache.store(SimpleNamespace(session='2018-01-02', security_id='SYNTHETIC', ticker='SYNTHETIC',
                               raw_close=12.5, signal_close=13.), 'FROZEN_SOURCE_PACKET')
    def original(*a, **k): raise Temporal('LIVE_ANCHOR_OUTSIDE_WINDOW: SYNTHETIC')
    cache.original = original
    buffer = SimpleNamespace(current=SimpleNamespace(day='2020-02-03', bars=()), rings={},
                             axis=['2020-01-31']*300)
    def prepare(*a, **k):
        bar = cache.retained(buffer, state, 'SYNTHETIC', state.feed['series']['SYNTHETIC']['signal_basis_anchor'])
        return SimpleNamespace(bars=(), signal_basis_anchors={'SYNTHETIC': bar},
                               window_features=dict(sessions=list(buffer.axis)))
    buffer.prepare = prepare
    return cache, buffer, SimpleNamespace(state=state)


def test_two_real_novel_source_uses_write_disjoint_proofs_and_chain(tmp_path):
    cache, buffer, run = case(tmp_path)
    try:
        gate = module.AnchorQualification(tmp_path, cache)
        paths = []
        for i, date in enumerate(('2018-01-02', '2018-01-03')):
            cache.records['SYNTHETIC'] = cache.records['SYNTHETIC'].model_copy(update={'session': date})
            run.state.feed['series']['SYNTHETIC']['signal_basis_anchor'][0] = date
            gate.prepare(buffer, run)
            assert len(gate.pending['source_falsifiers']) == 2
            gate.after(run, SimpleNamespace(state=SimpleNamespace(last_processed_session=buffer.current.day,
                                                                  state_hash=str(i+2)*64)))
            paths.append(sorted((tmp_path/'anchor-qualifications').glob('*.json'))[-1])
        assert gate.commitment()['rows'] == 2 and len(set(paths)) == 2
        values = [json.loads(p.read_bytes()) for p in paths]
        assert values[1]['record']['previous_chain_sha256'] == values[0]['chain_sha256']
        assert all(v['record']['source_sha256'] == cache.source_sha256 for v in values)
        assert not (tmp_path/'actual-anchor-qualification.json').exists()
        assert gate.proofs == []
        assert module.verify_proofs(tmp_path, gate.commitment()) == values
        first = dict(gate.commitment(), rows=1, bytes=len((tmp_path/'anchor-qualifications/index.jsonl').read_bytes().splitlines(keepends=True)[0]),
                     chain_sha256=values[0]['chain_sha256'])
        first['prefix_sha256'] = hashlib.sha256((tmp_path/'anchor-qualifications/index.jsonl').read_bytes()[:first['bytes']]).hexdigest()
        with pytest.raises(ValueError, match='EXPLICIT_TAIL_POLICY'): module.verify_proofs(tmp_path, first)
        evidence = module.proof_prefix_evidence(tmp_path, first)
        assert evidence['committed_proofs'] == values[:1] and evidence['uncommitted_index']['bytes'] > 0
        assert set(evidence['uncommitted_proof_files']) == {paths[1].name}
        paths[0].write_bytes(paths[0].read_bytes() + b' ')
        with pytest.raises(ValueError, match='IMMUTABLE_PROOF_BYTES'):
            module.verify_proofs(tmp_path, gate.commitment())
    finally: cache.stream.close()


def test_original_still_reproduces_second_exclusive_save_failure(tmp_path):
    cache, buffer, run = case(tmp_path)
    try:
        gate = old.AnchorQualification(tmp_path, cache)
        gate.prepare(buffer, run)
        nxt = SimpleNamespace(state=SimpleNamespace(last_processed_session=buffer.current.day, state_hash='2'*64))
        gate.after(run, nxt)
        gate.seen.clear(); gate.prepare(buffer, run)
        with pytest.raises(FileExistsError): gate.after(run, nxt)
    finally: cache.stream.close()


def test_actual_adjacency_guard_and_removal_falsifier(tmp_path):
    cache, buffer, run = case(tmp_path)
    try:
        gate = module.AnchorQualification(tmp_path, cache); gate.prepare(buffer, run)
        bad = SimpleNamespace(state=SimpleNamespace(last_processed_session='2099-01-01', state_hash='2'*64))
        with pytest.raises(ValueError, match='CANONICAL_TRANSITION_ADJACENCY'): gate.after(run, bad)
        assert gate.commitment()['rows'] == 0
        tree = module.after_tree(); fn = tree.body[0]
        fn.body = [n for n in fn.body if not (isinstance(n, ast.Expr) and any(isinstance(v, ast.Constant)
            and v.value == 'PARALLEL_ACTUAL_ANCHOR_CANONICAL_TRANSITION_ADJACENCY' for v in ast.walk(n)))]
        scope = dict(vars(old)); exec(compile(tree, '<actual-adjacency-guard-removed>', 'exec'), scope)
        scope['after'](gate, run, bad)
        assert gate.commitment()['rows'] == 1
    finally: cache.stream.close()


def test_only_declared_save_and_memory_sites_change():
    old_fn = module.original_method('after'); new_fn = module.after_tree().body[0]
    assert 'PARALLEL_ACTUAL_ANCHOR_CANONICAL_TRANSITION_ADJACENCY' in ast.unparse(new_fn)
    assert 'self.seen.update' in ast.unparse(new_fn) and 'self.pending = None' in ast.unparse(new_fn)
    assert len(list(ast.walk(new_fn))) < len(list(ast.walk(old_fn)))
    assert hashlib.sha256(Path(old.__file__).read_bytes()).hexdigest() == module.ORIGINAL_SHA256


def test_seed_requires_exact_source_input_and_qualified_historical_record(tmp_path):
    cache, buffer, run = case(tmp_path)
    record = cache.records['SYNTHETIC'].model_dump()
    seed = dict(status=module.PROOF_STATUS, financial_authority=False,
                source_sha256=cache.source_sha256, input_sha256=cache.input_sha256,
                source_records={'SYNTHETIC': record},
                source_records_sha256=module.digest({'SYNTHETIC': record}), session='2020-01-02')
    try:
        good = tmp_path/'good'; good.mkdir()
        gate = module.AnchorQualification(good, cache, seed_proofs=[seed], predecessor={'artifact_id': 123})
        assert ('SYNTHETIC', '2018-01-02') in gate.seen
        bad = tmp_path/'bad'; bad.mkdir()
        with pytest.raises(ValueError, match='SEED_ONLY_AUTHENTICATED'):
            module.AnchorQualification(bad, cache, seed_proofs=[dict(seed, input_sha256='f'*64)])
    finally: cache.stream.close()
