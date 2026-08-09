"""Wealth Core, running inside Sentinel.

The engine itself is carried forward INTACT from
`stock_strategy_shared.wealth_core` and is not reimplemented here. This package
is the wiring: corpus in, target book out, with Sentinel's exposure pinned to
1.00 until the controller is certified (docs/sentinel-deployment.md §6).
"""
