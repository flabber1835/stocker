"""Strict retained-proof JSON and host evidence transfer refusal cases."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
from sentinel import retained_go, retained_parity, observation_startup as startup
from sentinel.authority import AuthorityRefused, canonical_sha256
from sentinel.strategy import production_strategy


def _distinct_price_input():
    from sentinel.core.session import PublishedSession, VendorBar, DefensiveBar
    published = PublishedSession(
        session='2026-09-14', data_version=7, meta={}, sectors={},
        bars=[VendorBar(session='2026-09-14', security_id='1', ticker='AAA',
            raw_open=19., raw_close=20., volume=1000000., signal_close=10.)],
        spy_closeadj=[600., 601.], spy_sessions=['2026-09-11', '2026-09-14'],
        spy_expected_sessions=['2026-09-11', '2026-09-14'],
        defensive_previous_bar=DefensiveBar('2026-09-11', 'SENTINEL:BIL', 'BIL', 91., 101., 121., 111.),
        defensive_bar=DefensiveBar('2026-09-14', 'SENTINEL:BIL', 'BIL', 92., 102., 122., 112.))
    return retained_parity.shadow._published_input_value(published)


def test_retained_decoder_keeps_spy_equity_and_bil_domains_separate():
    archived = _distinct_price_input()
    before = deepcopy(archived)
    published = retained_parity.decode(archived)
    assert published.spy_closeadj == [600., 601.]
    assert published.spy_sessions == published.spy_expected_sessions == ['2026-09-11', '2026-09-14']
    assert (published.bars[0].signal_close, published.bars[0].raw_open,
            published.bars[0].raw_close) == (10., 19., 20.)
    assert (published.defensive_previous_bar.open_signal, published.defensive_previous_bar.close_signal,
            published.defensive_previous_bar.close_adjusted, published.defensive_previous_bar.close_unadjusted) == (91., 101., 121., 111.)
    assert (published.defensive_bar.open_signal, published.defensive_bar.close_signal,
            published.defensive_bar.close_adjusted, published.defensive_bar.close_unadjusted) == (92., 102., 122., 112.)
    assert retained_parity.shadow._published_input_value(published) == archived == before


def test_retained_decoder_refuses_unconsumed_input_evidence():
    archived = _distinct_price_input()
    archived['unknown_price_domain'] = 999.
    with pytest.raises(RuntimeError, match='RETAINED_INPUT_ROUNDTRIP_CHANGED'):
        retained_parity.decode(archived)


@pytest.fixture
def evidence():
    controller, strategy = production_strategy()
    proof = {field: 'a'*64 for field in retained_parity.Proof.model_fields if field.endswith('sha256')}
    proof.update(schema=retained_parity.SCHEMA, authority_effect='NONE', scope=retained_parity.SCOPE,
        observation_id='primary', session='2026-09-14', checks={key: True for key in retained_parity.Checks.model_fields},
        strategy_sha256=canonical_sha256(strategy))
    warmup = {'schema': startup.RETAINED_SCHEMA, 'warmup_sessions': 299, 'measured_sessions': 1,
        'decision_session': proof['session'], 'result_state_sha256': proof['state_sha256'],
        'decision': {'observed': 'retained'}, 'retained': proof}
    warmup['decision_sha256'] = canonical_sha256(warmup['decision'])
    return warmup, dict(strategy_sha256=canonical_sha256(strategy), controller_sha256=controller.digest)


def test_retained_evidence_is_a_separate_valid_contract(evidence):
    warmup, bindings = evidence
    startup.require(warmup, **bindings)
    assert startup.feature_sessions(warmup['schema']) == 299
    assert startup.selected_contract()['schema'] == startup.WINDOW_FORMED_SCHEMA


@pytest.mark.parametrize('defect', ['scope', 'authority', 'unknown', 'false', 'integer', 'missing',
    'bad_hash', 'session', 'weekend', 'strategy', 'state', 'decision', 'formation', 'measured', 'fresh_label'])
def test_relabelled_or_malformed_retained_proof_cannot_be_admitted(evidence, defect):
    value, bindings = evidence
    value = deepcopy(value)
    proof = value['retained']
    if defect == 'scope': proof['scope'] = 'ROLLING_FORMED_STARTUP_AND_RESTART'
    elif defect == 'authority': proof['authority_effect'] = 'PAPER_EXECUTION_GO'
    elif defect == 'unknown': proof['new_field'] = 'ignored?'
    elif defect == 'false': proof['checks']['restart_equivalent'] = False
    elif defect == 'integer': proof['checks']['restart_equivalent'] = 1
    elif defect == 'missing': del proof['checks']['restart_equivalent']
    elif defect == 'bad_hash': proof['origin_sha256'] = 'not-a-hash'
    elif defect == 'session': proof['session'] = '2026-09-15'
    elif defect == 'weekend':
        proof['session'] = value['decision_session'] = '2026-09-12'
    elif defect == 'strategy': proof['strategy_sha256'] = 'b'*64
    elif defect == 'state': value['result_state_sha256'] = 'b'*64
    elif defect == 'decision': value['decision']['observed'] = 'changed'
    elif defect == 'formation': value['formation'] = {'sessions': 126}
    elif defect == 'measured': value['measured_sessions'] = 426
    else: value['schema'] = startup.WINDOW_FORMED_SCHEMA
    with pytest.raises(AuthorityRefused):
        startup.require(value, **bindings)


@pytest.mark.parametrize('raw', ['{"files":{},"files":{}}', '{"files":NaN}', '{"files":Infinity}'])
def test_untrusted_manifest_json_is_not_permissive(tmp_path, raw):
    path = tmp_path/'source.json'
    path.write_text(raw)
    with pytest.raises((ValueError, RuntimeError)):
        retained_go.load_manifest(path)


def test_host_reads_revision_without_broker_authority_and_mounts_exact_source(monkeypatch):
    import sentinel_go_24x7_entry as host
    revision = 'a'*40
    manifest = {'schema': 'sentinel.retained-source-manifest/1', 'revision': revision, 'files': {'x.py': 'b'*64}}
    calls = []
    class Runner:
        def run(self, argv, **kw):
            calls.append((argv, kw['env']))
            return subprocess.CompletedProcess(argv, 0, json.dumps({'retained_revision': revision}), '')
    loaded = []
    def exporter(path):
        loaded.append(path)
        return {'build': lambda **kw: manifest if kw['revision'] == revision else pytest.fail('wrong revision')}
    monkeypatch.setattr(host.runpy, 'run_path', exporter)
    with host._retained_manifest(Runner(), compose_args=[], env={'ALPACA_API_KEY': 'private', 'ALPACA_SECRET_KEY': 'private',
            'SENTINEL_PAPER_ACCOUNT_ID': 'private'}) as args:
        mounted = args[1].rsplit(':/retained/source.json:ro', 1)[0]
        assert json.loads(Path(mounted).read_text()) == manifest
        assert args[-1] == 'SENTINEL_RETAINED_SOURCE_MANIFEST=/retained/source.json'
    assert not Path(mounted).exists()
    assert calls[0][1] == {}
    assert calls[0][0][-1] == host._RETAINED_REVISION_CODE
    assert loaded == [str(host.go.ROOT/'tools/sentinel_retained_source_manifest.py')]


@pytest.mark.parametrize('raw,exit_code', [('{}', 0), ('[]', 0), ('{"retained_revision":"bad"}', 0),
    ('{"retained_revision":null,"retained_revision":null}', 0), ('{"retained_revision":null}', 2)])
def test_host_refuses_unproven_origin_before_financial_preparation(raw, exit_code):
    import sentinel_go_24x7_entry as host
    class Runner:
        def run(self, argv, **kw):
            return subprocess.CompletedProcess(argv, exit_code, raw, '')
    with pytest.raises(ValueError):
        with host._retained_manifest(Runner(), compose_args=[], env={}) as _:
            pytest.fail('unproven revision reached preparation')


@pytest.mark.parametrize('entry_point', ['controller', 'entry'])
@pytest.mark.parametrize('defect', [None, 'duplicate', 'parallel_fresh', 'changed_call'])
def test_actual_phase_contract_checks_single_retained_dispatcher(monkeypatch, entry_point, defect):
    import sentinel_go_24x7_entry as host
    import sentinel_go_phase_controller as controller
    import sentinel_go_phase_entry as entry
    check = (controller._install_single_preparation_contract if entry_point == 'controller'
             else entry._install_reviewed_preparation_contract)
    monkeypatch.setattr(controller.entry, 'install', lambda: None)
    code = host._PREPARATION_CODE
    assert code.count('retained_go.prepare(c, target_session=target,') == 1
    if defect == 'duplicate': code += '\nretained_go.prepare(c, target_session=target, absolute_deadline=None)'
    elif defect == 'parallel_fresh': code += '\nrolling_go_inputs.prepare(c, target_session=target)'
    elif defect == 'changed_call': code = code.replace('retained_go.prepare(c,', 'retained_go.prepare(None,')
    monkeypatch.setattr(controller.go, '_PREPARATION_CODE', code)
    if defect:
        with pytest.raises(controller.PhaseRefused): check()
    else:
        check()
