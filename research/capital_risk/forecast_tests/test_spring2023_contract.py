"""Frozen launch and source closure checks; no Docker or financial execution."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def test_one_exact_own_march_prefix_no_unadvanced_recovery_or_new_origin():
    request = json.loads((HERE / 'system-campaign-p02-spring2023-request.json').read_bytes())
    specraw = (HERE / request['predecessor_file']).read_bytes()
    spec = json.loads(specraw)
    assert hashlib.sha256(specraw).hexdigest() == request['predecessor_sha256']
    assert spec['run_id'] == 41174261514 and spec['selected_session'] == '2023-03-31'
    assert spec['outer_sha256'] == '6610e5e4ea3b39d8112d76c41303780b5172463172d46c2376079509bfcb48c5'
    assert len(spec['repairs']) == 29 and request['parent_certificate_rows'] == 867
    assert request['new_overlay'] and not request['new_origin'] and not request['source_conversion']
    assert request['concurrent_candidate_limit'] == 1 and request['only_candidate'] == 'P02'
    assert 'abiomed_unadvanced_equivalence_sha256' not in request


def test_diagnostic_changes_only_exact_known_entrypoint_and_retains_all_fences():
    original = (HERE / 'system_campaign_stopped_diagnostics.py').read_bytes()
    expected = original.replace(b'/driver/system_campaign_p02_abiomed_run.py',
                                b'/driver/system_campaign_p02_spring2023_run.py')
    actual = (HERE / 'system_campaign_p02_spring2023_diagnostics.py').read_bytes()
    assert actual == expected and original != expected
    request = json.loads((HERE / 'system-campaign-p02-spring2023-request.json').read_bytes())
    assert request['diagnostic_driver_sha256'] == hashlib.sha256(actual).hexdigest()


def test_cash_catalog_claims_and_actual_source_closure_are_explicit():
    request = json.loads((HERE / 'system-campaign-p02-spring2023-request.json').read_bytes())
    raw = (HERE / 'system-campaign-spring2023-cash-calendar-terminal-facts.json').read_bytes()
    cat = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == request['spring2023_cash_catalog_sha256']
    assert len(cat['terms']) == 13 and len(cat['same_day_quote_claims']) == 1
    assert cat['same_day_quote_claims'][0]['session'] == '2023-04-27'
    assert cat['same_day_quote_claims'][0]['security_id'] == '858933953652218125'
    assert len(request['sources']) == 189
    for name in ['system_campaign_spring2023_preflight.py', 'system_campaign_spring2023_gate.py',
                 'system_campaign_spring2023_review.py', 'system_campaign_spring2023_basis.py',
                 'system_campaign_p02_spring2023_run.py', 'system_campaign_p02_spring2023_job.py',
                 'system_campaign_p02_spring2023_diagnostics.py']:
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == request['sources'][name]


def test_one_request_path_trigger_unchanged_single_candidate_concurrency_and_encrypted_paths():
    repo = HERE.parents[1]
    wf = (repo / '.github/workflows/capital-system-p02-spring2023-cash.yml').read_text()
    assert "paths: ['research/capital_risk/system-campaign-p02-spring2023-request.json']" in wf
    assert 'group: system-optimization-002-p02-only' in wf and 'cancel-in-progress: false' in wf
    assert wf.count('system_campaign_p02_spring2023_job.py --request') == 1
    assert wf.count('retention-days: 7') == 2
    assert 'p02-uncertainty.tar.crseal' in wf and 'p02-stopped-diagnostics.tar.crseal' in wf
    assert 'book/' not in wf and 'worker.log' not in wf and 'daily.jsonl' not in wf
    tree = ast.parse((HERE / 'system_campaign_p02_spring2023_job.py').read_bytes())
    main, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == 'stopped_run']
    assert len(calls) == 2  # One financial worker, then its independent reviewer.
