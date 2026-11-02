"""Source-bound job transport checks only; no Docker or financial execution."""
import ast
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import system_campaign_discovery_spinoff_job as j


def test_successor_keeps_all426_sources_and_selects_only_own_two_arms():
    value = j.expected_request()
    assert value['arms'] == ['P06', 'P07'] and value['concurrent_candidate_limit'] == 2
    assert len(value['sources']) == 431
    assert set(j.original.expected_request()['sources']).issubset(value['sources'])
    assert value['source_bound_spinoff_deferral_selected']
    assert value['published_bars_and_quotes_unchanged']
    assert value['no_spinoff_receipt_liquidation_cash_or_receivable']
    assert not value['canonical_financial_source_changed'] and not value['financial_state_adopted']
    assert set(value['diagnostic_predecessors']) == {'P06', 'P07'}
    assert all('cash' not in descriptor and 'price' not in descriptor for descriptor in value['diagnostic_predecessors'].values())


def test_frozen_main_namespace_selects_exact_successor_without_changing_stop_or_crypto():
    fn = j.method('main', dict(SELECTED_ARMS=j.SELECTED_ARMS, expected_request=j.expected_request,
        worker_command=j.worker_command, inspect=j.inspect))
    assert fn.__globals__['SELECTED_ARMS'] == ('P06', 'P07')
    assert fn.__globals__['expected_request'] is j.expected_request
    assert fn.__globals__['worker_command'] is j.worker_command
    assert fn.__globals__['inspect'] is j.inspect
    for name in ('qualify_export', 'finish_export', 'stopped_run', 'phase'):
        assert fn.__globals__[name] is getattr(j.original, name)


def test_worker_keeps_readonly_inputs_offline_two_cpu_eight_gib(monkeypatch, tmp_path):
    monkeypatch.setattr(j.original.os, 'getuid', lambda: 1001, raising=False)
    monkeypatch.setattr(j.original.os, 'getgid', lambda: 1001, raising=False)
    for arm in j.SELECTED_ARMS:
        command = j.worker_command('capital-system-diagnostic-suffix-'+arm.lower()+'-worker-123-1', arm,
            tmp_path/'source', tmp_path/'frozen', tmp_path/'out', tmp_path/'old', tmp_path/'previous')
        assert command[command.index('-B'):] == j.entrypoint(arm)
        assert command[command.index('--network')+1] == 'none'
        assert command[command.index('--memory')+1] == command[command.index('--memory-swap')+1] == '8g'
        assert command[command.index('--cpus')+1] == '2'
        assert any('target=/old,readonly' in item for item in command)
        assert any('target=/previous,readonly' in item for item in command)
        assert any('target=/variant,readonly' in item for item in command)
        assert any('target=/frozen,readonly' in item for item in command)
    with pytest.raises(ValueError): j.entrypoint('P05')
