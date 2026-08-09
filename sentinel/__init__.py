"""Sentinel — the deterministic exposure controller that replaces Stocker.

Stocker is retired as a runtime (tag `stocker-legacy-2026-08`). New operational
logic belongs here; retired Stocker services do not gain new behaviour. See
docs/sentinel-deployment.md for the operational ground truth and
docs/sentinel-architecture.md for the architecture.

Nothing in this package imports a Stocker SERVICE. It reuses Stocker's proven
COMPONENTS — the broker adapter, and later the Wealth Core engine — which is the
distinction the retirement draws: the components are carried forward, the runtime
is not.
"""
