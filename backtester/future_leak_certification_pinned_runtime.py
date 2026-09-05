#!/usr/bin/env python3
"""Run the future-leak suite against the exact pinned runtime API surface."""
from __future__ import annotations

import sys

import sentinel.core.production as production
from backtester import future_leak_certification as base


# The pinned authority predates the kernel/session module extraction. The
# transition implementation is production.advance_state at this exact SHA.
production.advance_session = production.advance_state
sys.modules["sentinel.core.kernel"] = production
sys.modules["sentinel.core.session"] = production


def main() -> int:
    return int(base.main())


if __name__ == "__main__":
    raise SystemExit(main())
