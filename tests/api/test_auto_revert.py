"""Auto-revert — a promotion is a REVERSIBLE experiment.

Auto-promotion was a one-way door: a candidate that cleared the gate became the
live config and stayed until some LATER candidate displaced it, and nothing
measured whether the switch helped. That forced the gate to carry all the
weight (when being wrong is permanent, the bar must be high — which is what
makes the loop slow) and left the switching POLICY unmeasured.

This suite locks the decision rule and the safety properties of applying it.
The decision function is pure, so the interesting boundaries — too little data,
a hair-thin edge, one outlier day carrying the mean — are tested directly
rather than only through a live deploy.
"""
import json
import os
import shutil
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import yaml

from app import main
from app.revert import RevertVerdict, revert_decision, weighted_return

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
V2 = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")
CORE = os.path.join(ROOT, "strategies", "quality_core_v1.yaml")


# ── the decision rule (pure) ────────────────────────────────────────────────

class TestRevertDecision:
    def _pairs(self, champ, disp, n):
        return [(champ, disp)] * n

    def test_reverts_when_the_displaced_config_persistently_leads(self):
        v = revert_decision(self._pairs(0.01, 0.05, 20),
                            min_sessions=20, margin=0.02)
        assert v.revert and v.n_days == 20
        assert v.avg_spread == pytest.approx(0.04)
        assert v.days_displaced_ahead == 20

    def test_too_few_spans_never_reverts(self):
        """Absence of evidence must not move the live config."""
        v = revert_decision(self._pairs(0.0, 0.9, 19), min_sessions=20, margin=0.02)
        assert not v.revert and "need 20" in v.reason

    def test_no_data_at_all_is_fail_closed(self):
        v = revert_decision([], min_sessions=20, margin=0.02)
        assert not v.revert and v.n_days == 0

    def test_an_edge_inside_the_margin_is_not_enough(self):
        """A revert is itself a config change with turnover cost — it has to
        clear noise, not merely register it."""
        v = revert_decision(self._pairs(0.01, 0.025, 25),
                            min_sessions=20, margin=0.02)
        assert not v.revert and "inside the" in v.reason

    def test_one_outlier_day_cannot_carry_the_mean(self):
        """THE whipsaw guard. 19 days where the champion wins slightly, one day
        where it is crushed: the mean says revert, the majority says the edge is
        not persistent. Reverting on a single day is exactly the churn the
        orphan timers exist to prevent."""
        pairs = [(0.01, 0.005)] * 19 + [(-0.60, 0.10)]
        mean_spread = sum(d - c for c, d in pairs) / len(pairs)
        assert mean_spread > 0.02, "fixture no longer reproduces the outlier case"
        v = revert_decision(pairs, min_sessions=20, margin=0.02)
        assert not v.revert
        assert "only 1/20" in v.reason
        assert v.days_displaced_ahead == 1

    def test_a_bare_majority_with_a_real_margin_does_revert(self):
        pairs = [(0.0, 0.09)] * 11 + [(0.0, -0.01)] * 9
        v = revert_decision(pairs, min_sessions=20, margin=0.02)
        assert v.revert and v.days_displaced_ahead == 11

    def test_exactly_half_is_not_a_majority(self):
        pairs = [(0.0, 0.20)] * 10 + [(0.0, -0.01)] * 10
        v = revert_decision(pairs, min_sessions=20, margin=0.02)
        assert not v.revert

    def test_none_entries_are_dropped_not_counted_as_zero(self):
        """A day with no priced return is missing data, not a tie."""
        pairs = [(0.01, 0.05)] * 20 + [(None, 0.05), (0.01, None)]
        v = revert_decision(pairs, min_sessions=20, margin=0.02)
        assert v.n_days == 20

    def test_a_negative_margin_is_refused(self):
        """It would revert on the champion merely being level — a config-writing
        rule must not accept a setting that makes it fire on nothing."""
        with pytest.raises(ValueError):
            revert_decision([(0.0, 0.0)] * 30, min_sessions=20, margin=-0.01)

    def test_verdict_is_immutable(self):
        with pytest.raises(Exception):
            RevertVerdict(True, "x").revert = False


class TestWeightedReturn:
    def test_renormalizes_over_priced_names_only(self):
        """An unpriced name must not silently count as 0% — that would flatter
        whichever side has more missing data."""
        assert weighted_return({"A": 0.5, "B": 0.5}, {"A": 0.10}) == pytest.approx(0.10)

    def test_weights_are_respected(self):
        r = weighted_return({"A": 0.75, "B": 0.25}, {"A": 0.10, "B": 0.02})
        assert r == pytest.approx(0.08)

    def test_none_when_nothing_is_priced(self):
        assert weighted_return({"A": 1.0}, {}) is None
        assert weighted_return({}, {"A": 0.1}) is None


# ── applying it: the safety properties ──────────────────────────────────────

class _Resp:
    def __init__(self, payload, status_code=200, text=""):
        self._p, self.status_code, self.text = payload, status_code, text

    def json(self):
        return self._p


class _FakeHttpx:
    def __init__(self, resp):
        self._resp = resp
        outer = self

        class _Client:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, **k):
                outer.last_posted = json
                return outer._resp
        self.AsyncClient = _Client


class _FakeEngine:
    def __init__(self):
        self.executed = []
        outer = self

        class _Conn:
            async def execute(self, stmt, params=None):
                outer.executed.append((str(stmt), params))
        self._conn = _Conn()

    @asynccontextmanager
    async def begin(self):
        yield self._conn

    @asynccontextmanager
    async def connect(self):
        yield self._conn


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    cfg = tmp_path / "active.yaml"
    shutil.copy(V2, cfg)
    monkeypatch.setattr(main, "STRATEGY_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(main, "ARTIFACTS_PATH", str(tmp_path / "artifacts"))
    monkeypatch.setattr(main, "engine", _FakeEngine())
    return cfg


def _write_promotion(tmp_path, cfg: dict, ph="abcd1234abcd1234"):
    d = tmp_path / "artifacts" / "bt"
    d.mkdir(parents=True, exist_ok=True)
    (d / "promotion.json").write_text(json.dumps({
        "config": cfg, "config_hash": ph, "hypothesis": "t",
        "diff_vs_active": {}, "evidence": {}}))
    return ph


@pytest.mark.asyncio
async def test_applying_a_promotion_stores_the_displaced_champion(sandbox, tmp_path):
    """Without this file the promotion is not revertible-by-measurement — the
    pipeline has nothing to shadow and the revert path nothing to restore."""
    before = open(sandbox).read()
    cand = yaml.safe_load(open(sandbox))
    cand["portfolio_builder"]["max_positions"] = 20
    _write_promotion(tmp_path, cand)
    with patch.object(main, "httpx", _FakeHttpx(_Resp({"valid": True}))):
        await main._check_promotion()

    dpath = main._displaced_config_path()
    assert os.path.exists(dpath), "displaced champion not stored"
    assert open(dpath).read() == before, "displaced config must be byte-exact"
    state = main._read_promo_state()
    assert state["displaced_hash"] == main._hash_raw(before)
    assert state["displaced_at"]


@pytest.mark.asyncio
async def test_a_reverted_candidate_can_never_be_re_promoted(sandbox, tmp_path):
    """PING-PONG GUARD. The lane re-promotes the same winning candidate the next
    evening; without the blocklist the config oscillates forever."""
    cand = yaml.safe_load(open(sandbox))
    cand["portfolio_builder"]["max_positions"] = 20
    ph = _write_promotion(tmp_path, cand)
    main._write_promo_state({"last_hash": "something-else",
                             "reverted_hashes": [ph]})
    before = open(sandbox).read()
    with patch.object(main, "httpx", _FakeHttpx(_Resp({"valid": True}))):
        await main._check_promotion()
    assert open(sandbox).read() == before, "a reverted candidate was re-applied"


@pytest.mark.asyncio
async def test_no_displaced_file_means_nothing_to_evaluate(sandbox):
    """The file's EXISTENCE is the signal that a promotion is under evaluation.
    With none, the watcher must be a complete no-op."""
    before = open(sandbox).read()
    await main._check_revert()
    assert open(sandbox).read() == before


@pytest.mark.asyncio
async def test_revert_restores_the_displaced_config_and_blocklists_the_promotion(
        sandbox, tmp_path, monkeypatch):
    displaced_raw = open(CORE).read()
    dpath = main._displaced_config_path()
    os.makedirs(os.path.dirname(dpath), exist_ok=True)
    with open(dpath, "w") as f:
        f.write(displaced_raw)
    main._write_promo_state({"last_hash": "promo-hash-1",
                             "displaced_hash": main._hash_raw(displaced_raw),
                             "displaced_at": "2026-06-01T00:00:00+00:00"})

    async def _pairs(*a, **k):
        return [(0.0, 0.05)] * 25
    monkeypatch.setattr(main, "_paired_spans", _pairs)
    with patch.object(main, "httpx", _FakeHttpx(_Resp({"valid": True}))):
        await main._check_revert()

    assert open(sandbox).read() == displaced_raw, "config not restored verbatim"
    state = main._read_promo_state()
    assert "promo-hash-1" in state["reverted_hashes"]
    assert state["status"] == "reverted"
    # Only the MOST RECENT promotion is revertible — chaining would walk the
    # config backwards through history on accumulated noise.
    assert state["displaced_hash"] is None
    assert not os.path.exists(dpath)
    assert any("auto_revert" in sql for sql, _ in main.engine.executed)


@pytest.mark.asyncio
async def test_revert_is_validator_gated(sandbox, tmp_path, monkeypatch):
    """'It ran live before' is an assumption, and this is still an automated
    write to the live strategy."""
    dpath = main._displaced_config_path()
    os.makedirs(os.path.dirname(dpath), exist_ok=True)
    with open(dpath, "w") as f:
        f.write(open(CORE).read())
    main._write_promo_state({"last_hash": "p1", "displaced_hash": "h",
                             "displaced_at": "2026-06-01T00:00:00+00:00"})

    async def _pairs(*a, **k):
        return [(0.0, 0.05)] * 25
    monkeypatch.setattr(main, "_paired_spans", _pairs)
    before = open(sandbox).read()
    with patch.object(main, "httpx",
                      _FakeHttpx(_Resp({"valid": False, "errors": ["x"]}, 422))):
        await main._check_revert()
    assert open(sandbox).read() == before, "reverted past the validator"
    assert os.path.exists(dpath), "displaced file cleared without reverting"


@pytest.mark.asyncio
async def test_a_losing_displaced_champion_leaves_the_promotion_alone(
        sandbox, monkeypatch):
    dpath = main._displaced_config_path()
    os.makedirs(os.path.dirname(dpath), exist_ok=True)
    with open(dpath, "w") as f:
        f.write(open(CORE).read())
    main._write_promo_state({"last_hash": "p1", "displaced_hash": "h",
                             "displaced_at": "2026-06-01T00:00:00+00:00"})

    async def _pairs(*a, **k):
        return [(0.05, 0.0)] * 25          # champion winning
    monkeypatch.setattr(main, "_paired_spans", _pairs)
    before = open(sandbox).read()
    await main._check_revert()
    assert open(sandbox).read() == before
    assert main._read_promo_state().get("status") != "reverted"
