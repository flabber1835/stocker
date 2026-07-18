"""Evaluator Phase 3 UI — the Review tab's Apply button and its wiring.

Static contract checks on dashboard.js + the dashboard backend proxies:
the Apply path must send confirm:true with the report's run_id, applied
recommendations must render as a badge instead of a second Apply button,
and invalid/advice cards must never get a button.
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "services" / "dashboard" / "static" / "dashboard.js").read_text()
PY = (ROOT / "services" / "dashboard" / "app" / "main.py").read_text()


def test_backend_proxies_exist():
    assert '@app.post("/api/config/apply")' in PY
    assert '@app.get("/api/config/changes")' in PY
    assert f"{{API_URL}}/config/apply" in PY


def test_apply_sends_confirm_and_source_report():
    m = re.search(r"async function applyRecommendation\(idx\)\s*\{(.*?)\n\}", JS, re.S)
    assert m, "applyRecommendation() missing"
    body = m.group(1)
    assert "confirm: true" in body
    assert "source_report_run_id: rep.run_id" in body
    assert "recommendation_index: idx" in body
    # a browser confirm() dialog guards the click
    assert "confirm(" in body and "LIVE strategy config" in body


def test_cards_gate_button_on_validity_and_applied_state():
    m = re.search(r"items\.map\(\(it, idx\) => \{(.*?)\}\)\.join", JS, re.S)
    assert m, "recommendation card renderer missing"
    card = m.group(1)
    # applied badge suppresses the button; advice/invalid cards get neither
    assert "_appliedChanges.find" in card
    assert "APPLIED" in card
    assert "applyRecommendation(' + idx + ')" in card
    assert re.search(r"isAdvice \|\| invalid \? ''", card), \
        "advice/invalid recommendations must not render an Apply button"


def test_loader_fetches_applied_changes():
    assert "_loadAppliedChanges()" in JS
    assert "/api/config/changes" in JS


def test_paired_apply_batch_flow():
    """Coupled edits (each alone schema-invalid) apply as ONE atomic batch:
    checkboxes on selectable cards, a footer button when >=2 exist, and a
    function that sends the checked fields as `changes` with confirm."""
    # checkbox rendered only on valid, unapplied cards; counted for the footer
    assert 'class="eval-rec-cb" data-idx=' in JS
    assert "selectableCount++" in JS and "selectableCount >= 2" in JS
    assert "applySelectedRecommendations()" in JS
    m = re.search(r"async function applySelectedRecommendations\(\)\s*\{(.*?)\n\}", JS, re.S)
    assert m, "applySelectedRecommendations() missing"
    body = m.group(1)
    assert "changes[it.config_field] = it.suggested_value" in body
    assert "changes: changes" in body and "confirm: true" in body
    assert "source_report_run_id: rep.run_id" in body
    # guarded: needs >=2 real selections, and a confirm dialog before writing
    assert "idxs.length < 2" in body
    assert "ATOMICALLY" in body
