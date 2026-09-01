"""Backtester certification package.

The explicit package boundary prevents ``tests/backtester`` from shadowing the
runtime package during pytest collection.

The pinned production source used by certification recently moved the pure
session transition's ``plan_session`` owner from ``sentinel.core.production``
to ``sentinel.core.kernel``. The retained strict-PIT certification wrapper
instruments that function to capture authenticated decision-boundary evidence.
Install one narrow bridge here so the wrapper instruments the current owner and
all kernel calls pass through the same instrumented function.
"""
from __future__ import annotations


def _bind_current_production_plan_session() -> None:
    try:
        import sentinel.core.kernel as kernel
        import sentinel.core.production as production
    except ImportError:
        # Lightweight source-only tools can import the backtester package before
        # the pinned production closure is present. The real replay imports it
        # after --main-root/PYTHONPATH binding and receives the bridge then.
        return

    if hasattr(production, "plan_session"):
        return

    original = kernel.plan_session
    production.plan_session = original

    def through_certification_owner(*args, **kwargs):
        return production.plan_session(*args, **kwargs)

    kernel.plan_session = through_certification_owner


_bind_current_production_plan_session()
del _bind_current_production_plan_session
