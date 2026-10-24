"""The single production strategy selector shared by paper and shadow paths."""
from sentinel.controller.champion_config import load
from sentinel.core.decision import runtime_strategy_identity
from sentinel.core.strategy_profiles import controller_for_identity


def production_strategy():
    from sentinel.controller.owned_impairment import load as owned
    from sentinel.core.window_policy import POLICY, FORMATION
    from sentinel.core.cash_distributions import POLICY as CASH_POLICY
    controller = owned()
    return controller, {**runtime_strategy_identity(controller), 'market_input_policy': POLICY,
                        'startup_policy': FORMATION,
                        'cash_distribution_policy': CASH_POLICY}


def owned_impairment_strategy():
    """Explicit access to the selected Owned55 profile."""
    from sentinel.controller.owned_impairment import load as owned
    controller = owned()
    return controller, runtime_strategy_identity(controller)
