"""The new namespaced entry point retains every reviewed host admission guard."""
import ast
import hashlib
from pathlib import Path


def test_dashboard_host_driver_changes_only_reviewed_namespace_and_receipt_kind():
    root = Path(__file__).resolve().parents[2]
    prior = (root / 'scripts/sentinel_chain_progress_recovery.py').read_bytes()
    assert hashlib.sha256(prior).hexdigest() == 'e2cfa7e5a1f2b4319ca3cf6ecffa41f099cd57ec117decda919abc2702d58eef'
    expected = prior.decode().replace('restored progress-migration witness', 'restored dashboard-migration witness')
    for old, new in (
        ('progress-witness', 'dashboard-ddl-witness'),
        ('sentinel.chain_progress_recovery', 'sentinel.panel.review_coverage_recovery'),
        ('sentinel.chain-progress-coverage-transfer/1', 'sentinel.dashboard-ddl-coverage-transfer/1'),
        ('progress coverage transfer', 'dashboard DDL coverage transfer'),
    ):
        expected = expected.replace(old, new)
    actual = (root / 'scripts/sentinel_dashboard_coverage_recovery.py').read_text()
    assert actual == expected
    assert ast.dump(ast.parse(actual)) == ast.dump(ast.parse(expected))
