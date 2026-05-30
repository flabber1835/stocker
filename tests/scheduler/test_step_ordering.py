"""
Tests that the scheduler _STEPS chain has vetter positioned before portfolio-builder.

The ordering matters because portfolio-builder reads vetter_exclusions to drop
flagged tickers. If vetter runs after portfolio-builder it cannot feed the same
cycle's build.
"""
import sys
import types
from unittest.mock import MagicMock


def _make_apscheduler_stubs():
    schedulers_pkg = types.ModuleType("apscheduler.schedulers")
    asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    asyncio_mod.AsyncIOScheduler = MagicMock()
    sys.modules.setdefault("apscheduler", types.ModuleType("apscheduler"))
    sys.modules.setdefault("apscheduler.schedulers", schedulers_pkg)
    sys.modules.setdefault("apscheduler.schedulers.asyncio", asyncio_mod)
    triggers_pkg = types.ModuleType("apscheduler.triggers")
    cron_mod = types.ModuleType("apscheduler.triggers.cron")
    cron_mod.CronTrigger = MagicMock()
    interval_mod = types.ModuleType("apscheduler.triggers.interval")
    interval_mod.IntervalTrigger = MagicMock()
    sys.modules.setdefault("apscheduler.triggers", triggers_pkg)
    sys.modules.setdefault("apscheduler.triggers.cron", cron_mod)
    sys.modules.setdefault("apscheduler.triggers.interval", interval_mod)


_make_apscheduler_stubs()

from app.main import _STEPS, DateAnchor  # noqa: E402


def _step_names() -> list[str]:
    return [s.name for s in _STEPS]


class TestStepOrdering:
    """Verify the critical ordering constraints in the daily chain."""

    def test_vetter_before_portfolio_builder(self):
        """Vetter must run before portfolio-builder so exclusions feed the same cycle."""
        names = _step_names()
        assert "vet" in names, "vet step must exist in _STEPS"
        assert "portfolio-builder" in names, "portfolio-builder step must exist in _STEPS"
        assert names.index("vet") < names.index("portfolio-builder"), (
            "vet must come before portfolio-builder — "
            "got ordering: " + str(names)
        )

    def test_portfolio_builder_before_delta(self):
        """portfolio-builder must run before delta so target weights are available."""
        names = _step_names()
        assert names.index("portfolio-builder") < names.index("delta"), (
            "portfolio-builder must come before delta"
        )

    def test_pipeline_before_vetter(self):
        """pipeline (rank) must run before vetter so vetter has rankings to query."""
        names = _step_names()
        assert names.index("pipeline") < names.index("vet"), (
            "pipeline must come before vet"
        )

    def test_fetch_data_first(self):
        """fetch-data must be the first step."""
        assert _step_names()[0] == "fetch-data"

    def test_delta_last(self):
        """delta must be the final step."""
        assert _step_names()[-1] == "delta"

    def test_full_order(self):
        """Full chain: fetch-data → pipeline → vet → portfolio-builder → delta."""
        names = _step_names()
        assert names == ["fetch-data", "pipeline", "vet", "portfolio-builder", "delta"], (
            "Unexpected chain order: " + str(names)
        )

    def test_vet_is_mandatory(self):
        """Vetter must be mandatory: portfolio-builder refuses to build without vetter exclusions."""
        vet_step = next(s for s in _STEPS if s.name == "vet")
        assert vet_step.optional is False, (
            "vet step must be optional=False — vetter failure must block portfolio-builder "
            "so the portfolio is never built without vetter exclusions"
        )

    def test_no_trading_day_step_uses_started_at(self):
        """
        Any step with date_anchor=TRADING_DAY must NOT use 'started_at' as its date_field.

        When a step runs on a weekend, started_at[:10] is the weekend date (e.g.
        Saturday 2026-05-23), but TRADING_DAY targets the last trading day
        (Friday 2026-05-22).  Saturday != Friday → the step is perpetually 'idle'
        and the supervisor re-triggers it in an infinite loop on every weekend cold boot.

        Use a data/chain-date field instead (chain_date, portfolio_date, run_date) which the
        service sets to the trading day of the data being processed, not the wall-clock
        run time.
        """
        for step in _STEPS:
            if step.date_anchor is DateAnchor.TRADING_DAY:
                assert step.date_field != "started_at", (
                    f"Step '{step.name}' has date_anchor=TRADING_DAY but date_field='started_at'. "
                    f"On weekends started_at is the weekend date, not the trading day, so the "
                    f"step will be 'idle' forever.  Use a data/chain-date field (chain_date, "
                    f"portfolio_date, run_date) that the service sets to the trading day."
                )

    def test_portfolio_builder_uses_portfolio_date(self):
        """portfolio-builder must use portfolio_date, not started_at."""
        pb = next(s for s in _STEPS if s.name == "portfolio-builder")
        assert pb.date_field == "portfolio_date", (
            f"portfolio-builder.date_field must be 'portfolio_date', got {pb.date_field!r}. "
            "portfolio_date is set to the trading day of the underlying ranking data; "
            "started_at is the wall-clock time and breaks on weekend cold boots."
        )

    def test_delta_uses_run_date(self):
        """delta step must use run_date, not started_at."""
        delta = next(s for s in _STEPS if s.name == "delta")
        assert delta.date_field == "run_date", (
            f"delta.date_field must be 'run_date', got {delta.date_field!r}. "
            "run_date is set to the trading day being processed; "
            "started_at is the wall-clock time and breaks on weekend cold boots."
        )
