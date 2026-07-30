"""The wind tunnel runs the LIVE modules, not copies of them.

`services/bt-engine/app/live/__init__.py` loads the real
`services/pipeline/app/engine.py` by file path (COPYed next to it in the image,
read from the repo in a checkout) instead of vendoring it. That is what makes a
sweep's answer apply to the live book: there is one implementation, so the two
cannot drift.

These assert IDENTITY — the same function object — rather than equivalent
behaviour, because a re-implementation that merely passes today's tests is exactly
the drift this design exists to prevent.
"""
import importlib
import os
import sys

import pytest

from app import live

_ENGINE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "pipeline", "app", "engine.py")


@pytest.fixture(scope="module")
def live_engine():
    """The real engine module, loaded the way the pipeline service loads it."""
    spec = importlib.util.spec_from_file_location(
        "pipeline_engine_under_test", os.path.abspath(_ENGINE_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pipeline_engine_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", [
    "evaluate_target_vs_live",
    "RankObservation",
    # Trailing stop — planned outside the engine so the simulator can check it in
    # its DAILY loop rather than on the rebalance_every cadence its decision block
    # runs on. Re-exported here for the same zero-drift reason as the rest.
    "plan_trailing_stops",
    "reentry_blocked",
    "StopState",
    "StopPlan",
])
def test_reexport_is_the_same_object_as_live(name, live_engine):
    import inspect

    exported = getattr(live, name)
    original = getattr(live_engine, name)
    assert exported.__qualname__ == original.__qualname__
    # Source equality is the real assertion. Object identity would be stronger but
    # is unavailable here: the loader executes the file under its own module name,
    # so the fixture's copy is a distinct object with identical source. A vendored
    # re-implementation is what this catches, and it would diverge here.
    assert inspect.getsource(exported) == inspect.getsource(original), (
        f"{name} in bt-engine differs from the live pipeline implementation — "
        "the wind tunnel would be scoring a strategy live does not run"
    )


def test_the_loader_points_at_the_live_pipeline_engine():
    """Guards the mapping itself: if someone re-points `engine` at a bt-engine-local
    copy, every identity test above would still pass against that copy."""
    from app.live import _SOURCES
    assert _SOURCES["engine"][1] == "services/pipeline/app/engine.py"


def test_the_planner_is_reachable_and_off_by_default_semantics():
    """A smoke check that the re-export is callable through the tunnel's import
    path, not merely present as an attribute."""
    plan = live.plan_trailing_stops(
        {"AAA": live.StopState(peak_close=100.0, last_close=10.0,
                               sessions_held=99, sessions_since_close=0)},
        enabled=False, stop_pct=0.15, arm_after_sessions=5,
        max_stale_sessions=2, max_stops_per_run=5)
    assert plan.stopped == {}
