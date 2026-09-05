"""Pytest compatibility binding for the pinned pre-extraction runtime authority.

The pinned runtime owns the pure transition in sentinel.core.production. Some
newer test modules import the later kernel/session module names. This plugin
aliases those names to the exact pinned module in-process and adds no economic
implementation.
"""
from __future__ import annotations

import sys

import sentinel.core.production as production


production.advance_session = production.advance_state
sys.modules["sentinel.core.kernel"] = production
sys.modules["sentinel.core.session"] = production
