"""Gate provenance carries the IDENTITY of the config that produced a number.

A baseline re-ran, its excess-vs-SPY moved 2.5pp, and separating "the config
changed" from "the rebalance grid shifted a day" required reading a filesystem
mtime — evidence a `git checkout` or a redeploy would have destroyed. The sweep
recorded only `base_strategy` (the strategy NAME), which is constant across
every config change, so the database could not answer the question at all.

The identity of a measurement's input is not optional metadata, and the
yardstick is the worst place to omit it: auto-promotion measures against it.
"""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "services", "bt-engine"))
os.environ.setdefault("BT_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/x")

from app.parity import config_identity, run_provenance  # noqa: E402
from stock_strategy_shared.loader import load_strategy  # noqa: E402
from stock_strategy_shared.schemas.strategy import StrategyConfig  # noqa: E402

ACTIVE = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")


def _cfg(**over) -> StrategyConfig:
    cfg, _ = load_strategy(ACTIVE)
    if not over:
        return cfg
    d = cfg.model_dump(mode="json")
    for path, val in over.items():
        node = d
        parts = path.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = val
    return StrategyConfig(**d)


class TestConfigIdentity:
    def test_it_is_deterministic(self):
        assert config_identity(_cfg()) == config_identity(_cfg())

    def test_the_drift_change_that_started_this_moves_the_hash(self):
        """The exact edit whose effect could not be attributed."""
        a = config_identity(_cfg())
        b = config_identity(_cfg(**{"delta_engine.rebalance_drift_threshold": 0.02}))
        assert a["config_hash"] != b["config_hash"]

    def test_the_strategy_name_alone_would_NOT_have_caught_it(self):
        """Why `base_strategy` was insufficient: the name is invariant under
        every config change, so recording it answered nothing."""
        a, b = _cfg(), _cfg(**{"delta_engine.rebalance_drift_threshold": 0.02})
        assert a.strategy_id == b.strategy_id
        assert config_identity(a)["config_hash"] != config_identity(b)["config_hash"]

    def test_it_hashes_CONTENT_not_file_bytes(self):
        """Reformatting the YAML must not read as a strategy change, and an
        inline config must hash the same as the file that would produce it."""
        cfg, file_hash = load_strategy(ACTIVE)
        ident = config_identity(cfg)
        assert ident["config_hash"] != file_hash          # different mechanisms
        assert config_identity(StrategyConfig(**cfg.model_dump(mode="json"))) == ident

    def test_it_matches_the_evaluators_candidate_hashing(self):
        """Same algorithm as queue_strategy_experiment, so a baseline hash and a
        candidate hash are directly COMPARABLE — that equality is what makes
        'which config was this measured against?' answerable."""
        import hashlib
        import json
        d = _cfg().model_dump(mode="json")
        expected = hashlib.sha256(
            json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]
        assert config_identity(_cfg())["config_hash"] == expected

    def test_a_broken_config_object_never_breaks_a_run(self):
        class Bad:
            def model_dump(self, **_):
                raise RuntimeError("boom")
        assert config_identity(Bad()) == {"config_hash": None, "strategy_id": None}


class TestProvenanceCarriesIt:
    def test_identity_rides_along_with_the_gate_state(self):
        p = run_provenance(_cfg())
        assert set(p) >= {"parity_enforced", "coverage_enforced",
                          "config_hash", "strategy_id"}
        assert p["strategy_id"] == "momentum_rotation_v2"

    def test_no_config_still_returns_gate_state(self):
        """Callers that genuinely have no config must not lose the gate stamp —
        the promotion gate reads those keys and refuses when they are absent."""
        p = run_provenance()
        assert p["parity_enforced"] in (True, False)
        assert "config_hash" not in p


def test_the_sweep_records_identity_in_the_spec_and_the_response():
    """The spec used to carry `base_strategy` only. Both the persisted row and
    the response matter: the row answers the question later, the response is how
    bt-scheduler stamps the lane entry at fire time."""
    src = open(os.path.join(ROOT, "services", "bt-engine", "app", "main.py")).read()
    i = src.index("INSERT INTO bt_sweeps")
    assert "_base_identity" in src[i:i + 900], "spec does not record config identity"
    j = src.index('"status": "started", "sweep_id": sweep_id')
    assert "_base_identity" in src[j:j + 300], "response does not return identity"


def test_the_lane_stamps_it_on_the_baseline_entry():
    src = open(os.path.join(ROOT, "services", "bt-scheduler", "app", "main.py")).read()
    i = src.index('"kind": "baseline"')
    assert "config_hash" in src[i:i + 800], "baseline entry records no config"
    # A candidate authored its own config; the engine's value must not clobber it.
    assert "not entry.get(k)" in src
