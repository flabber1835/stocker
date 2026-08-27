"""Wealth Core v1 — the canonical, stateful strategy engine.

ONE implementation. The live book, the wind tunnel and the backtester all call
these functions; they differ only in adapters (data source, clock, execution,
persistence). Nothing here touches a database, a clock, or the network — the
whole engine is a pure function of (session, state, market data, config), which
is what makes cross-engine parity testable rather than aspirational.

SPECIFICATION PROVENANCE. Every rule implemented here traces to the written
Wealth Core v1 assignment of 2026-08-03. The five cited research artifacts
(CERTIFIED_SHARADAR_WEALTH_REPORT.md, STOCKER_WEALTH_CORE_V1.yaml,
CERTIFIED_SHARADAR_SYMBOLIC_REPORT.md, WEALTH_ACCUMULATION_STRATEGY.yaml,
REPRODUCIBILITY_MANIFEST.json) did NOT reach this repository and are not the
source of anything below. Where the assignment forced a choice it does not
state, the choice is a named configuration field with a documented default and
is listed in docs/wealth-core-v1.md under "unresolved details" — never inlined
as a silent constant.
"""
from stock_strategy_shared.wealth_core.signals import (  # noqa: F401
    DurableScore,
    annualized_formation_volatility,
    durable_score,
    medium_term_momentum,
    rank_candidates,
    recent_return,
    top_decile_cutoff,
)

STRATEGY_ID = "stocker_wealth_core_v1"
RESEARCH_ALIAS = "stocker_durable_compounder_v1"
STRATEGY_VERSION = 1

# Persistence is a financial boundary. Importing any Wealth Core submodule first
# executes this package initializer, so install the strict nested-state decoder
# here once and make direct ``wealth_core.state`` imports equally protected.
from stock_strategy_shared.wealth_core.state_restore_hardening import (  # noqa: E402
    install as _install_state_restore_hardening,
)

_install_state_restore_hardening()
del _install_state_restore_hardening
