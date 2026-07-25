"""The shadow challenger must actually be able to RUN.

It had never produced a single row. The reason turns out to be a trap: the
shadow re-ranks the champion's PERSISTED factor scores, so a challenger whose
`factor_engine` differs is refused — and EVERY strategy YAML in the repo except
the active one differs there. "Just set CHALLENGER_CONFIG_PATH" would therefore
have yielded zero rows and one stdout line, which is indistinguishable from the
feature being switched off.

Same failure class as the day's other bugs: a path that looks enabled, does
nothing, and reports it only where nobody looks.
"""
from pathlib import Path

import pytest
import yaml

from stock_strategy_shared.loader import load_strategy

ROOT = Path(__file__).resolve().parents[2]
STRATEGIES = ROOT / "strategies"
COMPOSE = ROOT / "docker-compose.yml"


def _active_path() -> Path:
    """The config the compose file actually pins for the pipeline."""
    txt = COMPOSE.read_text()
    line = next(ln for ln in txt.splitlines()
                if "STRATEGY_CONFIG_PATH:" in ln and "momentum" in ln)
    return STRATEGIES / line.split("/strategies/")[1].split()[0]


def _challenger_path() -> Path | None:
    txt = COMPOSE.read_text()
    line = next((ln for ln in txt.splitlines()
                 if "CHALLENGER_CONFIG_PATH:" in ln), None)
    if not line or "/strategies/" not in line:
        return None
    return STRATEGIES / line.split("/strategies/")[1].split("}")[0].strip()


def test_the_configured_challenger_is_shadow_compatible():
    """THE guard. A challenger whose factor_engine differs is silently refused
    every single day — the shadow would accumulate nothing forever."""
    ch_path = _challenger_path()
    assert ch_path is not None, "no challenger configured in docker-compose.yml"
    assert ch_path.exists(), f"challenger {ch_path.name} does not exist"
    active, _ = load_strategy(str(_active_path()))
    chal, _ = load_strategy(str(ch_path))
    assert chal.factor_engine.model_dump() == active.factor_engine.model_dump(), (
        f"{ch_path.name} differs from the active config in factor_engine — the "
        "pipeline will refuse it on every run and the shadow will never produce "
        "a row. Change weights/builder knobs instead, or send it to the wind "
        "tunnel, which recomputes factors.")


def test_the_challenger_actually_differs_from_the_champion():
    """A challenger identical to the champion measures nothing."""
    active, ah = load_strategy(str(_active_path()))
    chal, ch = load_strategy(str(_challenger_path()))
    assert ah != ch, "challenger is byte-identical to the champion"
    assert (chal.static_factor_weights.model_dump()
            != active.static_factor_weights.model_dump()), \
        "challenger does not change any factor weight"


def test_challenger_weights_are_a_valid_vector():
    chal, _ = load_strategy(str(_challenger_path()))
    w = [v for v in chal.static_factor_weights.model_dump().values() if v]
    assert abs(sum(w) - 1.0) < 1e-6, f"weights sum to {sum(w)}, not 1.0"


def test_refusal_is_persisted_not_just_printed():
    """A stdout line nobody reads is indistinguishable from 'switched off'. The
    refusal must land in shadow_runs so the packet can explain the absence."""
    src = (ROOT / "services" / "pipeline" / "app" / "main.py").read_text()
    i = src.index("shadow SKIPPED")
    window = src[i:i + 1600]
    assert "INSERT INTO shadow_runs" in window, \
        "the factor_engine refusal is printed but never persisted"
    assert "'skipped'" in window


def test_packet_distinguishes_unconfigured_from_refused():
    """'No successful rows' has two causes with opposite fixes: nothing
    configured, versus a challenger being refused every day. Reporting the
    second as the first sends the reader to fix something that is not broken."""
    src = (ROOT / "services" / "evaluator" / "app" / "packet.py").read_text()
    i = src.index("async def _shadow_vs_champion")
    body = src[i:i + 4000]
    assert "status <> 'success'" in body, "packet never looks for refused rows"
    assert "refusals" in body


@pytest.mark.parametrize("name", [p.name for p in STRATEGIES.glob("*.yaml")])
def test_every_strategy_yaml_still_loads(name):
    """Cheap breakage guard — a new challenger must not break config loading."""
    load_strategy(str(STRATEGIES / name))


def test_challenger_is_documented_as_the_pending_recommendation():
    """The challenger under test is the evaluator's own standing call, which
    the experiment lane has never validated. Keep that rationale visible."""
    txt = (STRATEGIES / _challenger_path().name).read_text()
    assert "CHALLENGER" in txt
    assert "factor_engine must be IDENTICAL" in txt
    raw = yaml.safe_load(txt)
    assert raw["static_factor_weights"]["momentum"] == 0.28
    assert raw["static_factor_weights"]["low_volatility"] == 0.18
    assert raw["static_factor_weights"]["quality"] == 0.24
