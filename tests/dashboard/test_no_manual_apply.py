"""The human one-click apply path is GONE (owner decision).

A config change reaches the live strategy ONLY by winning the wind-tunnel gate.
These assert the UI can no longer offer a manual apply — the old Apply buttons
and their POST /config/apply calls must not come back by accident.
"""
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
JS = os.path.join(ROOT, "services", "dashboard", "static", "dashboard.js")


def _js() -> str:
    with open(JS) as f:
        return f.read()


def test_no_apply_endpoint_call_in_ui():
    src = _js()
    assert "/api/config/apply" not in src
    assert "applyRecommendation" not in src
    assert "applySelectedRecommendations" not in src


def test_no_apply_buttons_rendered():
    src = _js()
    assert "eval-apply-btn" not in src
    assert "Apply selected together" not in src


def test_applied_changes_history_still_shown():
    # the audit trail of what the AUTOMATED promotions applied stays visible
    assert "/api/config/changes" in _js()


def test_no_server_side_apply_proxy():
    """The UI check above only covers the JS. The dashboard also kept the
    server-side proxy that forwarded to the api's POST /config/apply — an
    endpoint that no longer exists, so the route could only 404 while still
    advertising a capability the system deliberately removed."""
    with open(os.path.join(ROOT, "services", "dashboard", "app", "main.py")) as f:
        src = f.read()
    assert '@app.post("/api/config/apply")' not in src
    assert "proxy_config_apply" not in src
