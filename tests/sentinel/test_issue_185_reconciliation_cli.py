"""Production installations cannot mint archive cursor authority from a retired source."""
from pathlib import Path
import os


def test_operator_has_no_network_reconciliation_or_mutation_bootstrap_command():
    root = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
    assert not (root / "scripts/sentinel_reconcile_sep.py").exists()
    entry = (root / "scripts/sentinel_go_preparation_runtime.py").read_text()
    assert "retained_go.prepare(c," in entry
    assert "establish_sep_cursor_after_complete_reconciliation" not in entry
