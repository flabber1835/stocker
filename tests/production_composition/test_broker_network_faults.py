from __future__ import annotations

from pathlib import Path
import sys
import urllib.error

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_go_validate as go  # noqa: E402

ENV = {
    "ALPACA_API_KEY": "fixture-key",
    "ALPACA_SECRET_KEY": "fixture-secret",
    "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
}
NOW = "2026-09-11T05:00:00Z"


@pytest.mark.parametrize("kind", ["timeout", "dns", "401", "429", "500", "503"])
def test_alpaca_partial_outage_never_becomes_account_pass(kind):
    def urlopen(request, timeout=20):
        assert request.get_method() == "GET"
        assert timeout == 20
        if kind == "timeout":
            raise TimeoutError("fixture timeout")
        if kind == "dns":
            raise urllib.error.URLError("temporary failure in name resolution")
        status = int(kind)
        raise urllib.error.HTTPError(
            request.full_url, status, "fixture", hdrs=None, fp=None)

    gate, subjects = go.probe_alpaca_account(
        env=dict(ENV), now_text=NOW, urlopen=urlopen)

    assert gate.status != go.PASS
    assert not subjects
    public = str(gate.to_dict())
    assert ENV["ALPACA_API_KEY"] not in public
    assert ENV["ALPACA_SECRET_KEY"] not in public


class MalformedResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b"not-json"


def test_alpaca_malformed_success_response_is_not_treated_as_account_authority():
    gate, subjects = go.probe_alpaca_account(
        env=dict(ENV), now_text=NOW,
        urlopen=lambda _request, timeout=20: MalformedResponse())
    assert gate.status != go.PASS
    assert not subjects


def test_shadow_target_account_preflight_remains_broker_free_by_contract():
    source = (ROOT / "scripts" / "sentinel_go_account_preflight.py").read_text(
        encoding="utf-8")
    shadow_branch = source[source.index('if target == "SHADOW"'):]
    assert "SKIPPED for SHADOW target" in shadow_branch
    assert shadow_branch.index("return 0") < shadow_branch.index("probe_alpaca_account")
