#!/usr/bin/env python3
"""Probe replay-evidence collection; this never invokes the final certifier."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

EXPECTED_SOURCE_HASH = 'e6af5674a34c3fc1d856aed343199d71ada04dc6db8fad2bed0507799b3afd10'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-file', required=True, type=Path)
    parser.add_argument('--replay-evidence', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source_hash = hashlib.sha256(args.source_file.read_bytes()).hexdigest()
    assert source_hash == EXPECTED_SOURCE_HASH
    spec = importlib.util.spec_from_file_location('exact_certificate_collector', args.source_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity = json.loads(args.replay_evidence.read_text())['identity']
    assert identity['source_sha'] == '27bb992087182c42c3c051e62bf837895f5d2ab7'
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'summary.json').write_text(json.dumps({
            'status': 'PASS', 'canonical_pit_dataset_hash': identity['dataset_hash']}))
        (root / 'metadata_authority_audit.json').write_text(json.dumps({
            'current_SHARADAR_TICKERS_economically_active_fields': [],
            'financial_grade': {'requires_resolved_nav': True,
                                'missing_leadership_return_policy': 'FAIL_CLOSED',
                                'dividend_lag_sessions': 15}}))
        result = module.collect_replay_evidence(mode='research', identity=identity, output_root=root)
        assert result['checks']['financial_semantics'] == 'PASS'
        assert result['checks']['checkpoint_resume'] == 'PASS'
        assert result['annual_chain'] is None
        evidence = {
            'scope': 'EVIDENCE_COLLECTOR_UNIT_FIXTURE_NOT_FINALIZER_CERTIFICATE',
            'source_sha': identity['source_sha'], 'source_file_sha256': source_hash,
            'execution_python': sys.version.split()[0],
            'files_supplied': sorted(p.name for p in root.iterdir()),
            'real_replay_executed': False, 'checkpoint_exercised': False,
            'accounting_ledger_supplied': False, 'checks_returned': result['checks'],
            'annual_chain': result['annual_chain'],
            'evidence_file_names': list(result['evidence_sha256']),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
