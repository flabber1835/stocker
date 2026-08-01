"""The factor step and the preview must assemble their inputs from ONE loader.

`load_factor_inputs` is a verbatim extraction of `_do_calculate` steps 1-5b. Its
whole reason to exist is that `POST /preview/factors` scores a candidate config
over exactly the inputs the live chain uses — a preview with its own loaders
would report a data difference as a config effect, which is the failure mode the
parity manifests exist to prevent.

Nothing enforces that by construction, so these tests pin the two properties that
matter: `_do_calculate` obtains its inputs THROUGH the loader (it has not grown a
second copy), and the loader itself writes nothing.
"""
import inspect
import re

import app.factor_inputs as fi
import app.main as pm


def test_do_calculate_gets_its_inputs_from_the_loader():
    src = inspect.getsource(pm._do_calculate)
    assert "load_factor_inputs(" in src, (
        "_do_calculate no longer calls load_factor_inputs — if the loaders were "
        "re-inlined, the preview is now scoring a different universe than the chain"
    )


def test_do_calculate_does_not_reimplement_the_loader_queries():
    """A cheap structural guard: the SELECTs the loader owns must not reappear in
    the caller. Catches a copy-paste 'just this one extra field' divergence."""
    src = inspect.getsource(pm._do_calculate)
    for fragment in (
        "FROM universe_snapshots",
        "FROM universe_tickers",
        "FROM daily_prices",
        "FROM fundamentals",
        "FROM earnings",
    ):
        assert fragment not in src, f"_do_calculate re-queries {fragment} itself"


def test_the_loader_only_reads():
    """It is called by a read-only HTTP preview. A write here would make that
    endpoint persist a run under a candidate config nobody approved."""
    src = inspect.getsource(fi)
    for verb in ("INSERT INTO", "UPDATE ", "DELETE FROM", "engine.begin("):
        assert verb not in src, f"factor_inputs performs a write ({verb!r})"


def test_the_loader_is_the_only_place_that_names_the_fundamentals_columns():
    """FUND_DF_COLUMNS is the single source; the caller must not re-list them."""
    src = inspect.getsource(pm._do_calculate)
    assert not re.search(r'"shares_outstanding_prior"', src)


def test_universe_override_is_the_only_behavioural_seam():
    """Everything else must be identical for both callers — audit logging and
    progress are injected precisely so the READ path cannot diverge."""
    params = inspect.signature(fi.load_factor_inputs).parameters
    assert list(params) == ["engine", "strategy", "universe_override", "log", "progress"]
    assert params["universe_override"].default is None
    assert params["log"].default is None
    assert params["progress"].default is None
