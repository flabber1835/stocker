"""progress_cb: the simulator and every caller must agree on the signature.

    _run_bg.<locals>._cb() takes 2 positional arguments but 3 were given

POST /jobs/run died ~5% in with that, for months. Commit 194b63d changed
`progress_cb(done, total)` to `progress_cb(done, total, stats)` and updated the
SWEEP callback but not the single-run one. Nothing noticed because the
experiment lane drives /sweeps/run — the broken path is the one a HUMAN uses,
which is exactly the path with no automated exercise.

A runtime test would need a full simulation to reach the callback (it fires
inside the day loop, past data loading), so it is checked structurally instead:
count what the simulator PASSES, count what each callback ACCEPTS, and require
them to be compatible.
"""
import ast
import inspect
import os

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SIM = os.path.join(ROOT, "services", "bt-engine", "app", "sim.py")
MAIN = os.path.join(ROOT, "services", "bt-engine", "app", "main.py")
SWEEP = os.path.join(ROOT, "services", "bt-engine", "app", "sweep.py")


def _sim_call_arity() -> int:
    """How many positional args run_simulation passes to progress_cb."""
    with open(SIM) as f:
        tree = ast.parse(f.read())
    arities = {len(n.args) for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and getattr(n.func, "id", None) == "progress_cb"}
    assert arities, "no progress_cb(...) call found in sim.py — did it move?"
    assert len(arities) == 1, f"sim.py calls progress_cb with varying arity: {arities}"
    return arities.pop()


def _callbacks(path: str) -> dict[str, ast.arguments]:
    """Every locally-defined `_cb`/`cb` — the shape passed as progress_cb."""
    with open(path) as f:
        tree = ast.parse(f.read())
    return {f"{path.split('/')[-1]}:{n.name}:{n.lineno}": n.args
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name in ("_cb", "cb")}


def _accepts(args: ast.arguments, n: int) -> bool:
    """Can this signature take n positional arguments?"""
    if args.vararg:
        return True
    positional = args.posonlyargs + args.args
    required = len(positional) - len(args.defaults)
    return required <= n <= len(positional)


def test_the_simulator_passes_three_arguments():
    """Pinned so a future change to the call site is a deliberate decision that
    updates this test, not a silent break of every caller."""
    assert _sim_call_arity() == 3


@pytest.mark.parametrize("path", [MAIN, SWEEP], ids=["main", "sweep"])
def test_every_progress_callback_accepts_what_the_simulator_passes(path):
    n = _sim_call_arity()
    cbs = _callbacks(path)
    assert cbs, f"no progress callbacks found in {path}"
    bad = []
    for where, args in cbs.items():
        # The sweep's outer _cb takes (phase, done, total, stats) and is wrapped
        # before reaching the simulator — allow any signature that can take the
        # simulator's arity OR that arity plus a leading phase.
        if not (_accepts(args, n) or _accepts(args, n + 1)):
            names = [a.arg for a in args.posonlyargs + args.args]
            bad.append(f"{where} accepts {names}")
    assert not bad, (
        f"progress_cb is called with {n} positional args; these cannot take it: "
        + "; ".join(bad))


def test_the_single_run_callback_tolerates_a_missing_stats_argument():
    """Defensive default, so a caller still on the 2-arg shape does not crash the
    run. The failure this replaces cost a 9-minute run before surfacing."""
    args = None
    for where, a in _callbacks(MAIN).items():
        if "_run_bg" not in where and ":_cb:" in where:
            args = a if args is None else args
    # locate the single-run callback by its stats parameter
    cbs = [a for a in _callbacks(MAIN).values()
           if any(x.arg == "stats" for x in a.posonlyargs + a.args)]
    assert cbs, "no callback in main.py accepts a `stats` argument"
    assert any(a.defaults for a in cbs), (
        "the stats argument should carry a default so an older 2-arg call site "
        "degrades instead of raising mid-run")


def test_run_simulation_is_called_with_the_right_positional_count():
    """The other half of the seam: main.py passes progress_cb POSITIONALLY into
    asyncio.to_thread(run_simulation, ...), so an inserted parameter silently
    shifts every later argument."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "services", "bt-engine"))
    os.environ.setdefault("BT_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/x")
    from app.sim import run_simulation
    params = list(inspect.signature(run_simulation).parameters)
    # Order is load-bearing for the positional call sites in main.py.
    assert params[:5] == ["prices", "fundamentals", "sector_map", "config", "params"]
    assert params[5:] == ["progress_cb", "factor_cache", "listing_windows", "earnings"], (
        "run_simulation's optional parameters were reordered — every positional "
        "call site in main.py now passes the wrong thing")
