"""Exact input/state comparison and diagnostic role separation on inert DATA."""
from copy import deepcopy
import gzip
import importlib
import json
from pathlib import Path

import pytest

import core_volatility_control_equivalence as eq
from core_volatility_admit import extract
from core_volatility_job import require_continuation_stage
from research.capital_risk.forecast_tests.test_core_volatility import test_constructor_and_actual_inspector_on_inert_docker_dto as constructor_canary


def test_original_compiler_and_observer_bodies_stay_bytecode_identical():
    for model, (name, _, _, _) in eq.SOURCES.items():
        original = importlib.import_module(name)
        window = 'DECEMBER' if model in ('SODA', 'SONC') else model
        prepare, observer = eq.compiler(model, 'a'*64, window)
        for left, right in ((prepare, original.prepare), (observer, original.observer)):
            assert left.__code__.co_code == right.__code__.co_code
            assert left.__code__.co_names == right.__code__.co_names
            assert left.__code__.co_varnames == right.__code__.co_varnames


def test_control_history_guard_rejects_owned_aaap_and_foreign_role():
    cp = {'sha256': 'a'*64, 'completed': 21, 'source_cursor': '2018-01-31',
          'run': {'state': {'wealth_core': {'episodes': {}}, 'pending': []}}}
    assert eq.control_scope(cp, 'CONTROL', 'a'*64, 'AAAP', 'AAAP') == []
    with pytest.raises(ValueError):
        eq.control_scope(cp, 'VOL075', 'a'*64, 'AAAP', 'AAAP')
    cp['run']['state']['pending'] = [{'security_id': eq.SOURCES['AAAP'][3]}]
    with pytest.raises(ValueError, match='UNOWNED_AND_UNORDERED'):
        eq.control_scope(cp, 'CONTROL', 'a'*64, 'AAAP', 'AAAP')


@pytest.mark.parametrize('field', ('state_sha256', 'account', 'controller', 'shares', 'type'))
def test_every_financial_controller_and_state_field_is_compared(field):
    a = {'input_sha256': 'a'*64, 'chain_sha256': 'b'*64, 'state_sha256': 'c'*64,
         'account': {'nav': '50000.00'}, 'controller': {'target': .55}, 'shares': 3}
    b = deepcopy(a)
    b['input_sha256'], b['chain_sha256'] = 'd'*64, 'e'*64
    assert eq.financial_difference(a, b) is None
    if field == 'type': b['shares'] = 3.
    elif field == 'account': b['account']['nav'] = '50000.01'
    elif field == 'controller': b['controller']['target'] = 1.
    elif field == 'shares': b['shares'] += 1
    else: b[field] = 'f'*64
    assert eq.financial_difference(a, b) is not None


def test_diagnostic_fork_preserves_numeric_hash_snapshot_and_exact_prefix(tmp_path):
    previous = tmp_path/'previous'
    book = previous/'book'
    (book/'repairs').mkdir(parents=True)
    (book/'identity.json').write_bytes(b'{"inert":true}\n')
    raw = b'{"inert":"repair"}\n'
    repair = eq.sha(raw)+'.json'
    (book/'repairs'/repair).write_bytes(raw)
    journal = b'{"inert":"committed"}\n'
    (book/'daily.jsonl').write_bytes(journal+b'UNCOMMITTED TAIL\n')
    cp = {'source_cursor': '2018-01-31', 'repairs': [{'filename': repair, 'sha256': eq.sha(raw)}],
          'journals': {'daily': {'bytes': len(journal), 'prefix_sha256': eq.sha(journal)}}}
    (book/'predecessor-checkpoints').mkdir()
    past = book/'predecessor-checkpoints'/('9'*64+'.json.gz')
    past.write_bytes(gzip.compress(json.dumps({'source_cursor': '2018-01-11'}).encode()))
    (book/'pre-event').mkdir()
    (book/'pre-event/2018-02-09-future.json.gz').write_bytes(b'FUTURE FILE MUST NOT BE PARSED')
    selected = book/'selected.json.gz'
    selected.write_bytes(gzip.compress(json.dumps(cp).encode()))
    destination = tmp_path/'diagnostic'
    eq.fork(previous, destination, selected, cp)
    assert (destination/'daily.jsonl').read_bytes() == journal
    assert (book/'daily.jsonl').read_bytes() == journal+b'UNCOMMITTED TAIL\n'
    assert (destination/'predecessor-checkpoints'/past.name).read_bytes() == past.read_bytes()
    assert not list((destination/'pre-event').iterdir())
    assert (destination/'repairs'/repair).read_bytes() == raw
    with (destination/'repairs'/repair).open('ab') as f:
        f.write(b'DIAGNOSTIC COPY ONLY')
    assert (book/'repairs'/repair).read_bytes() == raw


@pytest.mark.parametrize('review', (False, True))
def test_actual_diagnostic_entrypoint_is_inspected(monkeypatch, review):
    constructor_canary(monkeypatch, 'CONTROL', review, True, False, control_equivalence=True, maximum=54)


def test_financial_admission_refuses_diagnostic_before_opening_archive(tmp_path):
    with pytest.raises(ValueError, match='DIAGNOSTIC_NEVER_FINANCIAL_ROOT'):
        extract(tmp_path/'absent.zip', tmp_path/'root', b'KEY', {'control_equivalence': True})


def test_diagnostic_stage_never_claims_performance_or_continuation():
    request = {'stage': 'OWN_CONTROL_INPUT_EQUIVALENCE', 'maximum': 54}
    receipt = {'worker': {'exit_code': 0}, 'reviewer': {'exit_code': 0},
               'status': 'CONTROL_INPUT_EQUIVALENCE_REVIEWED_PENDING_TRANSPORT_ADMISSION'}
    outcome = {'schema': 'research.core-volatility-control-input-equivalence/1', 'diagnostic_only': True,
               'performance_admitted': False, 'financial_continuation_authorized': False,
               'financial_sessions_added_to_experiment': 0}
    require_continuation_stage(request, receipt, outcome, 'CONTROL')
    for field in ('performance_admitted', 'financial_continuation_authorized'):
        changed = dict(outcome, **{field: True})
        with pytest.raises(ValueError, match='DIAGNOSTIC_NEVER_FINANCIAL_CONTINUATION'):
            require_continuation_stage(request, receipt, changed, 'CONTROL')


def test_diagnostic_financial_entrypoint_stays_hosted(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_CORE_ONLY'):
        eq.run(Path('/previous'), 'CONTROL', 54)
