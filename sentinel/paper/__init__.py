"""Paper-trading lifecycle orchestration.

The package initializer is a declarative compatibility surface. Canonical
implementations live in the cohesive lifecycle modules.
"""

from __future__ import annotations

from sentinel import (
    binding as binding_mod,
    dual_plan_authority,
    identity as system_identity,
    informational_paper_mirror,
    schema,
    trial,
    trial_close,
    trial_fills,
)

from sentinel.controller.concordance_parent import load as load_concordance_parent

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution import commands as execution_commands

from sentinel.execution import preopen_authority

from sentinel.execution import target_reprojection

from sentinel.feed import calendar, publication, readiness, store as feed_store

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
    PreOpenShareUnitAuthorityUnavailable,
    PaperAccountInspection,
    PreparationResult,
    ExecutionResult,
)

from .inspection import (
    DEFENSIVE_SYMBOL,
    _require_certified_paper_broker,
    _inspection_account_or_refuse,
    inspect_paper_account,
    _account_evidence_is_quiescent,
    _account_or_refuse,
    _recovery_account_identity_or_refuse,
    build_security_resolver,
)

from .validation import (
    _assert_concordance_witness_authority,
    _hash,
    _readiness_or_refuse,
    _execution_window_or_refuse,
    _missed_sessions,
    _assert_deterministic_plan_id,
    _fresh_connection_factory,
    _validate_automation_grant,
    _validate_broker_grant,
    _guard_broker,
    _state_and_plan_or_refuse,
    _assert_plan_authorities,
)

from .cash import (
    ACCOUNT_ENDPOINT_LAG_GRACE,
    _ACCOUNT_ENDPOINT_LAG_SCHEMA,
    _ACCOUNT_ENDPOINT_LAG_PREFIX,
    _observation_economics,
    _account_economics,
    _account_endpoint_lag_is_live,
    _broker_cash_state_or_refuse,
    _cash_authority_or_refuse,
)

from .targets import (
    _action_lookup,
    _target_action_lookup,
    _target_action_multipliers,
    _post_projection_action_multipliers,
    _preopen_active_security_ids,
    _informational_active_symbols,
    _plan_deltas,
    _provably_clean_empty_noop,
    _preopen_views_or_none,
    _revalidate_preopen_authority_or_refuse,
    _official_preopen_cutoff,
    _target_projection_or_refuse,
    _instrument_map,
)

from .reconciliation import (
    _clean_or_refuse,
    _dual_mutation_observation_or_refuse,
    _settled_account_evidence_bracket,
)

from .finalization import (
    _record_due_close_nav_or_refuse,
    _record_due_fill_interval_or_refuse,
    _finalize_due_succeeded_cycle_or_refuse,
)

from .preparation import (
    SIMPLIFIED_LDRC_STRATEGY_ID,
    SIMPLIFIED_LDRC_STRATEGY_VERSION,
    _default_paper_strategy,
    _load_marks_and_tickers,
    _fresh_warmed_state,
    prepare_paper_plan,
    current_paper_plan,
)

from .execution import (
    _execution_observation_time,
    _execute_current_paper_plan,
    execute_paper_plan,
    execute_automated_paper_plan,
)

from .recovery import recover_automated_paper_cycle

__all__ = [
    "DEFENSIVE_SYMBOL",
    "ExecutionResult",
    "PaperAccountInspection",
    "PaperActivationRefused",
    "PaperRetryableRefused",
    "PreOpenShareUnitAuthorityUnavailable",
    "PreparationResult",
    "build_security_resolver",
    "current_paper_plan",
    "execute_automated_paper_plan",
    "execute_paper_plan",
    "inspect_paper_account",
    "prepare_paper_plan",
    "recover_automated_paper_cycle",
]
