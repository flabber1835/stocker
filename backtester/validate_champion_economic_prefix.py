#!/usr/bin/env python3
"""Validate existing bounded evidence; no strategy execution or data mutation.

The original reports promote shadow_equity/open_equity to named Wealth Core
columns. This explicit schema mapping repairs the initial post-replay validator.
All original observations and their hashes remain unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd
from pandas.testing import assert_frame_equal

try:
    from .champion_economic_prefix_audit import EXPECTED_CORPUS, normalized_ast
except ImportError:
    from champion_economic_prefix_audit import EXPECTED_CORPUS, normalized_ast

DIMENSIONS = {
    'candidate': 'NONE_OBSERVATION_ONLY',
    'certified': 'NONE_OBSERVATION_ONLY',
    'certified_capacity_off': 'EXECUTION_PARTICIPATION_CAP_ONLY',
    'certified_dividend_1': 'DIVIDEND_SETTLEMENT_LAG_ONLY',
    'certified_candidate_types': 'UNKNOWN_SECURITY_TYPE_CLASSIFICATION_ONLY',
}
REPORT_RENAMES = {'research_wealth_core_equity': 'shadow_equity',
                  'research_wealth_core_open_equity': 'open_equity'}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--original-candidate', required=True, type=Path)
    parser.add_argument('--original-certified', required=True, type=Path)
    args = parser.parse_args()
    root = args.root
    result = {'scope': 'BOUNDED_PREFIX_ONLY_NOT_CERTIFICATION',
              'validator_python': sys.version.split()[0],
              'original_run_id': 34042141867,
              'original_workflow_status': 'FAIL_POSTPROCESSING_COLUMN_NAME_KEYERROR',
              'recovery': 'OFFLINE_VALIDATION_OF_UNCHANGED_RETAINED_BYTES',
              'explicit_report_column_mapping': REPORT_RENAMES}
    identities = {}
    for case, dimension in DIMENSIONS.items():
        case_root = root / case
        for name, expected in json.loads((case_root / 'SHA256.json').read_text()).items():
            assert digest(case_root / name) == expected, (case, name)
        identity = json.loads((case_root / 'identity.json').read_text())
        assert identity['changed_dimension'] == dimension
        assert identity['status'] == 'PASS_BOUNDED_OBSERVATION'
        assert identity['initial_shadow_cash'] == 100000000
        assert identity['corpus_hash'] == EXPECTED_CORPUS
        assert identity['observer_stripped_ast_matches'] is True
        economic = (case_root / 'economic-generated.py').read_text()
        observed = (case_root / 'observed-generated.py').read_text()
        assert normalized_ast(economic) == normalized_ast(observed, strip_hooks=True)
        summary = json.loads((case_root / 'observation-summary.json').read_text())
        assert summary['sessions'] == 147 and summary['last_session'] == '2006-08-02'
        assert summary['failed_checks'] == 0
        identities[case] = identity
    for case, original in [('candidate', args.original_candidate), ('certified', args.original_certified)]:
        path = original / 'daily.csv.gz'
        expected = pd.read_csv(path).rename(columns=REPORT_RENAMES)
        expected = expected[expected.date <= '2006-08-02'].reset_index(drop=True)
        actual = pd.read_csv(root / case / 'observed-daily.csv').reset_index(drop=True)
        columns = sorted(set(expected.columns) & set(actual.columns))
        assert len(columns) == 30 and len(expected) == len(actual) == 3
        assert_frame_equal(expected[columns], actual[columns], check_dtype=False, rtol=1e-12, atol=1e-7)
        result[case] = {'status': 'PASS', 'sessions': 3, 'compared_columns': columns,
                        'first': str(actual.date.iloc[0]), 'last': str(actual.date.iloc[-1]),
                        'original_daily_sha256': digest(path),
                        'observed_daily_sha256': digest(root / case / 'observed-daily.csv')}
    retained = (args.original_candidate / 'generated-replay.py').read_text()
    rebuilt = (root / 'candidate/economic-generated.py').read_text()
    assert normalized_ast(retained) == normalized_ast(rebuilt)
    result['candidate_source_ast_matches_retained'] = True
    result['observer_stripped_asts_reverified'] = list(DIMENSIONS)
    result['tolerances'] = {'rtol': 1e-12, 'atol': 1e-7}
    (root / 'baseline-reproduction.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    (root / 'controlled-replay-identities.json').write_text(json.dumps(identities, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': 'PASS_OFFLINE_BASELINE_VALIDATION', 'columns': 30,
                      'sessions_per_baseline': 3, 'cases_reused': 5}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
