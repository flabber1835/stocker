"""Hosted DATA-only staged-sizing experiment, separate from all financial backtests."""
import argparse
import base64
import importlib.abc
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

from core_volatility_source import need, sha
from seal import sha256_file

HERE = Path(__file__).resolve().parent
DOC = 'docs/core-staged-sizing-diagnostic.md'
WORKFLOW = '.github/workflows/capital-core-staged-sizing-diagnostic.yml'
REQUEST = 'core-staged-sizing-diagnostic-request.json'


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_vacancy', 'research.pooled_input')):
            raise AssertionError('DIAGNOSTIC_CANONICAL_IMPORT_FORBIDDEN:'+fullname)


def expected_request():
    parent = json.loads((HERE/'core-volatility-gbt-parents.json').read_bytes())
    need(parent['arms']['VOL075']['completed'] == 1196
         and parent['arms']['VOL075']['checkpoint_sha256'] == '376b422e09e8cf01c682b674dfee80d5ff483c0b4a7fab6ddbf78472642b84af'
         and parent['admissions']['VOL075']['whole_cipher_authenticated_before_parsing'], 'EXACT_SIZING_STUDY_ADMITTED_PARENT')
    return dict(schema='research.core-staged-sizing-request/1', generation=1, stage='SIZING_DIAGNOSTIC',
        arm='VOL075', parent=parent['arms']['VOL075'], parent_admission=parent['admissions']['VOL075'],
        diagnostic_only=True, financial_continuation_authorized=False,
        cumulative_budget_fractions=['0.20', '0.50', '1.00'], gain_gates=['0.10', '0.20'],
        trailing_stop_unchanged='0.30', fractional_units=True, include_fees_and_observed_dividends=True,
        fixed_actual_entries=True, original_backtests_changed=False,
        protocol_sha256=sha256_file(HERE.parent.parent/DOC),
        workflow_sha256=sha256_file(HERE.parent.parent/WORKFLOW),
        sources={p.name: sha256_file(p) for p in sorted(HERE.iterdir())
                 if p.is_file() and p.suffix in ('.py', '.json', '.lock') and p.name != REQUEST})


def probe(request):
    need(json.loads(request.read_bytes()) == expected_request(), 'EXACT_SIZING_DIAGNOSTIC_SOURCE_CLOSURE')
    return dict(status='SIZING_DIAGNOSTIC_DATA_PROBE_PASSED', canonical_runtime_executed=False)


def inventory(root):
    need(not any(p.is_symlink() for p in root.rglob('*')), 'REGULAR_DIAGNOSTIC_INPUT')
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob('*')) if p.is_file()}


def run(request, output):
    from probe import check_context, admitted_output
    check_context(os.environ)
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'NO_UNCHANGED_DIAGNOSTIC_RERUN')
    probe(request)
    contract = expected_request()
    output = admitted_output(Path(os.environ['GITHUB_WORKSPACE']), output)
    output.parent.mkdir(parents=True, exist_ok=True)
    key = base64.b64decode(os.environ.pop('CAPITAL_RISK_RESEARCH_KEY_20261027', ''), validate=True)
    need(len(key) == 32, 'SIZING_DIAGNOSTIC_TRANSFER_KEY')
    root = Path(os.environ['RUNNER_TEMP'])/'core-staged-sizing-diagnostic-output'
    root.mkdir(mode=0o700)
    receipt = dict(schema='research.core-volatility-receipt/1', arm='VOL075', generation=1,
        stage='SIZING_DIAGNOSTIC', status='SIZING_DIAGNOSTIC_REFUSED',
        run_id=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(request), protocol_sha256=contract['protocol_sha256'],
        diagnostic_only=True, financial_continuation_authorized=False, performance_admitted=False,
        production_contacted=False, original_campaign_resumed=False)
    sys.meta_path.insert(0, NoCanonical())
    try:
        from core_volatility_admit import hosted as admit
        previous = admit(contract['parent'], Path(os.environ['RUNNER_TEMP'])/'core-volatility-transfer-sizing-diagnostic', key)
        before = inventory(previous)
        for p in previous.rglob('*'):
            os.chmod(p, 0o555 if p.is_dir() else 0o444)
        os.chmod(previous, 0o555)
        os.environ.pop('GH_TOKEN', None)
        from core_entry_sizing_diagnostic import replay, STATUS
        report = replay(previous/'book')
        need(inventory(previous) == before, 'READ_ONLY_SIZING_DIAGNOSTIC_INPUT_UNCHANGED')
        (root/'report.json').write_bytes((json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+'\n').encode())
        shutil.copyfile(request, root/'request.json')
        shutil.copyfile(previous.parent/'admission.json', root/'parent-artifact-admission.json')
        (root/'integrity.json').write_bytes((json.dumps(dict(parent_inventory_sha256=sha(json.dumps(before, sort_keys=True).encode()),
            parent_unchanged=True, canonical_imports_forbidden=True, new_financial_books=0,
            request_sha256=sha256_file(request)), sort_keys=True)+'\n').encode())
        receipt['status'] = STATUS
    except Exception as error:
        receipt['error_type'] = type(error).__name__
        (root/'exception-chain.txt').write_text(traceback.format_exc())
    finally:
        os.environ.pop('GH_TOKEN', None)
        from full_system_trials_job import seal
        receipt['encrypted_output'] = seal(root, output.parent/'core-staged-sizing-diagnostic.tar.crseal',
            key, request, 'VOL075', stage='campaign-candidate', protocol_sha256=contract['protocol_sha256'])
        key = None
        output.write_bytes((json.dumps(receipt, sort_keys=True, indent=2)+'\n').encode())
    print(json.dumps(receipt), flush=True)
    need(receipt['status'] == 'SIZING_DIAGNOSTIC_ONLY_NO_FINANCIAL_AUTHORITY', 'SUCCESSFUL_SIZING_DIAGNOSTIC_REQUIRED')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--request', type=Path, default=HERE/REQUEST)
    p.add_argument('--prepare', action='store_true')
    p.add_argument('--probe', action='store_true')
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    if a.prepare:
        need(not a.request.exists(), 'NEW_SIZING_DIAGNOSTIC_REQUEST')
        a.request.write_bytes((json.dumps(expected_request(), sort_keys=True, indent=2)+'\n').encode())
    elif a.probe:
        print(json.dumps(probe(a.request)))
    else:
        run(a.request, a.output)
