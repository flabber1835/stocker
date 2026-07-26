"""BT_DATA_MODE — a missing secret must not silently become synthetic data.

`is_mock()` used to be `BT_MOCK_DATA or not SHARADAR_API_KEY`. So a key that
failed to load substituted a tiny synthetic corpus, and every downstream number
stayed shaped like a real backtest — feeding a promotion gate that rewrites the
live strategy. Research credibility cannot rest on an env var loading.
"""
import importlib

import pytest


def _client(monkeypatch, **env):
    for k in ("BT_DATA_MODE", "BT_MOCK_DATA", "SHARADAR_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import app.sharadar_client as mod
    return importlib.reload(mod)


class TestFailLoudRatherThanDowngrade:
    def test_sharadar_without_a_key_fails_at_startup(self, monkeypatch):
        """THE bug. Previously this returned mock data and carried on."""
        c = _client(monkeypatch, BT_DATA_MODE="sharadar")
        with pytest.raises(c.DataModeError) as exc:
            c.verify_data_mode()
        assert "SHARADAR_API_KEY" in str(exc.value)
        assert "mock" in str(exc.value), "the error must say how to opt in"

    def test_a_missing_key_is_the_default_path(self, monkeypatch):
        """No BT_DATA_MODE set at all still defaults to sharadar — so an
        unconfigured deploy fails loudly instead of quietly going synthetic."""
        c = _client(monkeypatch)
        assert c.data_mode() == "sharadar"
        with pytest.raises(c.DataModeError):
            c.verify_data_mode()

    def test_explicit_mock_is_allowed_without_a_key(self, monkeypatch):
        c = _client(monkeypatch, BT_DATA_MODE="mock")
        assert c.verify_data_mode() == "mock"
        assert c.is_mock() is True

    def test_sharadar_with_a_key_is_real_mode(self, monkeypatch):
        c = _client(monkeypatch, BT_DATA_MODE="sharadar", SHARADAR_API_KEY="k")
        assert c.verify_data_mode() == "sharadar"
        assert c.is_mock() is False

    def test_a_key_present_but_mode_mock_still_serves_mock(self, monkeypatch):
        """Explicit beats incidental: having a key does not silently switch a
        deliberately-mock run to real data mid-experiment."""
        c = _client(monkeypatch, BT_DATA_MODE="mock", SHARADAR_API_KEY="k")
        assert c.is_mock() is True

    def test_legacy_bt_mock_data_is_still_honoured(self, monkeypatch):
        """Existing deployments set BT_MOCK_DATA=true; that is an EXPLICIT
        request and must keep working."""
        c = _client(monkeypatch, BT_MOCK_DATA="true")
        assert c.data_mode() == "mock" and c.is_mock() is True

    def test_an_unknown_mode_is_an_error_not_a_default(self, monkeypatch):
        """Silently treating a typo as 'sharadar' or 'mock' is how this class of
        bug started."""
        c = _client(monkeypatch, BT_DATA_MODE="sharader")   # typo
        with pytest.raises(c.DataModeError):
            c.data_mode()


def test_startup_verifies_before_serving(monkeypatch):
    """A check that exists but is never called is not a check."""
    import inspect
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "services" / "bt-data" / "app" / "main.py"
    body = src.read_text()
    i = body.index("async def lifespan")
    # inside lifespan, before the app yields
    lifespan = body[i:body.index("yield", i)]
    assert "verify_data_mode()" in lifespan
    assert "SYNTHETIC DATA" in lifespan, (
        "a mock-mode startup must be unmistakable in the log")


def test_the_mode_is_reported_on_every_job_response(monkeypatch):
    """After the fact, a report built from synthetic data has to be
    identifiable — otherwise 'was this real?' is unanswerable."""
    from pathlib import Path
    body = (Path(__file__).resolve().parents[2] / "services" / "bt-data"
            / "app" / "main.py").read_text()
    assert body.count('"data_mode": data_mode()') >= 3
