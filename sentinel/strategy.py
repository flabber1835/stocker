"""The single production strategy selector shared by paper and shadow paths."""
from sentinel.controller.median5 import load
from sentinel.core.decision import runtime_strategy_identity


def production_strategy():
    controller = load()
    return controller, runtime_strategy_identity(controller)
