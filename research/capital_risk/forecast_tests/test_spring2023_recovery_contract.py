"""Exact recovery wire-up, without importing the launcher or executing Core."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def test_same_financial_parent_and_cash_facts_plus_authenticated_unadvanced_attempt():
    old = json.loads((HERE / 'system-campaign-p02-spring2023-request.json').read_bytes())
    new = json.loads((HERE / 'system-campaign-p02-spring2023-recovery-request.json').read_bytes())
    assert new['predecessor_file'] == old['predecessor_file']
    assert new['predecessor_sha256'] == old['predecessor_sha256']
    assert new['spring2023_cash_catalog_sha256'] == old['spring2023_cash_catalog_sha256']
    assert new['parent_certificate_rows'] == old['parent_certificate_rows'] == 867
    proofraw = (HERE / 'system-campaign-p02-spring2023-unadvanced-equivalence.json').read_bytes()
    assert hashlib.sha256(proofraw).hexdigest() == new['spring2023_unadvanced_equivalence_sha256']
    proof = json.loads(proofraw)
    assert proof['failed_run_id'] == 41178393607 and proof['financial_parent_run_id'] == 41174261514
    assert proof['all_inventory_members_authenticated'] == 127 and len(proof['exact_unchanged_members']) == 7
    assert proof['financial_entry_not_reached'] and proof['new_input_not_adopted']


def test_only_unadopted_entrypoint_changes_among_inherited_driver_sources():
    old = json.loads((HERE / 'system-campaign-p02-spring2023-request.json').read_bytes())
    new = json.loads((HERE / 'system-campaign-p02-spring2023-recovery-request.json').read_bytes())
    changed = [n for n in old['sources'] if old['sources'][n] != new['sources'][n]]
    assert changed == ['system_campaign_p02_spring2023_run.py']
    added = set(new['sources']) - set(old['sources'])
    assert added == {'system_campaign_spring2023_sensor.py', 'system_campaign_spring2023_recovery.py',
                     'system-campaign-p02-spring2023-unadvanced-equivalence.json',
                     'system_campaign_p02_spring2023_recovery_job.py'}
    assert len(new['sources']) == 193
    for n in [*added, *changed]:
        assert hashlib.sha256((HERE / n).read_bytes()).hexdigest() == new['sources'][n]
    assert not new['new_origin'] and not new['source_conversion']


def test_constructor_receives_real_parent_and_original_typed_model_before_replay():
    tree = ast.parse((HERE / 'system_campaign_p02_spring2023_run.py').read_bytes())
    run, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run']
    ctor, = [n for n in ast.walk(run) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == 'SensorCertificate']
    values = {v.arg: ast.unparse(v.value) for v in ctor.keywords}
    assert values['parent_checkpoint'] == 'cp' and values['parent_spec'] == 'spec'
    assert values['abiomed_model'] == 'amodel'
    assert values['parent_certificate_raw'] == "(old / 'uncertainty-certificate.jsonl').read_bytes()"
    assert values['parent_review_raw'] == "(old / 'uncertainty-certificate-review.json').read_bytes()"
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert any(n.module == 'system_campaign_spring2023_sensor' for n in imports)
    for name in ('run', 'review'):
        fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == 'verify_unchanged_attempt' for n in ast.walk(fn))


def test_recovery_workflow_has_distinct_single_trigger_and_same_isolated_job():
    repo = HERE.parents[1]
    raw = (repo / '.github/workflows/capital-system-p02-spring2023-recovery.yml').read_text()
    assert "paths: ['research/capital_risk/system-campaign-p02-spring2023-recovery-request.json']" in raw
    assert 'group: system-optimization-002-p02-only' in raw and 'cancel-in-progress: false' in raw
    assert raw.count('system_campaign_p02_spring2023_recovery_job.py --request') == 1
    assert raw.count('retention-days: 7') == 2
    assert 'system-p02-spring2023-recovery-${{ github.sha }}' in raw
    assert 'system-p02-spring2023-recovery-diagnostics-${{ github.sha }}' in raw
    assert 'daily.jsonl' not in raw and 'book/' not in raw and 'worker.log' not in raw
