"""Pure resolution of named controller profiles, without runtime identity I/O."""
from sentinel.controller.champion_config import load


def controller_for_identity(identity):
    """Resolve the actual controller config for a named, digest-bound profile."""
    from sentinel.controller.frozen_rule import load as frozen
    from sentinel.controller.concordance_parent import load as concordance
    from sentinel.controller.median5 import load as median5
    from sentinel.controller.ex3_v6 import load as v5
    from sentinel.controller.owned_impairment import load as owned
    for factory in (owned, load, v5, median5, concordance, frozen):
        controller = factory()
        if controller.strategy_id == identity.get("strategy"):
            if controller.digest != identity.get("controller_rule_sha256"):
                raise ValueError("controller rule digest differs from strategy identity")
            return controller
    raise ValueError("strategy identity names an unsupported controller profile")
