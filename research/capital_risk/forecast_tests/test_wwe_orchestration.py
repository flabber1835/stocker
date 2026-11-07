"""Hosted-entry contract and retained metadata; never execute a financial book."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

import system_campaign_p02_wwe_job as job
from system_campaign_content_reference import reference
from system_campaign_facts import digest


def test_actual_request_selects_only_admitted_own_august_checkpoint():
    value = job.expected_request()
    spec = json.loads((job.HERE / value['predecessor_file']).read_bytes())
    assert spec['run_id'] == 41194712101 and spec['selected_session'] == '2023-08-31'
    assert len(spec['repairs']) == 33 and value['parent_certificate_rows'] == 972
    assert value['predecessor_sha256'] == job.sha256_file(job.HERE / value['predecessor_file'])
    assert value['parent_content_reference_sha256'] == digest(reference(spec))
    assert value['execution_mode'] == 'RETAINED_SIX_MODEL_WWE_STOCK_SUFFIX'
    assert value['new_origin'] is False and value['production_contacted'] is False


def test_all_223_already_adopted_driver_sources_are_byte_identical():
    old = job.inherited_request()
    current = job.expected_request()
    assert len(old['sources']) == 223 and len(current['sources']) == 236
    assert {name: current['sources'][name] for name in old['sources']} == old['sources']
    assert set(current['sources']) == set(job.SOURCES)
    assert current['qualified_packet_source_sha256'] == old['qualified_packet_source_sha256']
    assert current['canonical_controller_sources'] == old['canonical_controller_sources']
    assert current['ordinary_registry_sha256'] == old['ordinary_registry_sha256']


def test_actual_inspection_entrypoint_rejects_previous_driver_and_guard_removal(monkeypatch):
    name = 'capital-system-factual-p02-worker-1-1'
    correct = dict(Config=dict(Cmd=['-B', '-u', '/driver/system_campaign_p02_wwe_run.py',
        '--mode', 'economic', '--spec', '/out/spec.json',
        '--request', '/driver/system-campaign-p02-wwe-request.json']))
    returned = deepcopy(correct)
    monkeypatch.setattr(job, 'prior_inspect', lambda *args: returned)
    assert job.inspect(name) is returned
    returned['Config']['Cmd'][2] = '/driver/system_campaign_p02_outcome_run.py'
    with pytest.raises(ValueError): job.inspect(name)
    tree = ast.parse(Path(job.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'inspect']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant)
                      and a.value == 'WWE_EXACT_FINANCIAL_OR_REVIEW_ENTRYPOINT'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(job))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-wwe-entrypoint-guard-removal>', 'exec'), namespace)
    assert namespace['inspect'](name) is returned


def test_export_uses_reference_before_worker_and_never_recopies_opaque_zip():
    tree = ast.parse(Path(job.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    preserved, = [n for n in calls if ast.unparse(n.func) == 'preserve_content_reference']
    writes = [n for n in calls if ast.unparse(n.func) == 'stopped_run']
    assert preserved.lineno < min(n.lineno for n in writes)
    assert not any('preserve_ancestor' in ast.unparse(n.func) for n in calls)
    assert 'system_campaign_large_factual_admit' in Path(job.__file__).read_text(encoding='utf8')
