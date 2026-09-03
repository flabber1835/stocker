#!/usr/bin/env python3
"""Run the IWV historical holdings probe against BlackRock's older export endpoint.

The endpoint identifier is independently documented in public code from 2016. This wrapper
keeps legacy-endpoint evidence separate from the current endpoint experiment.
"""

from __future__ import annotations

import pit_iwv_holdings_probe as probe


probe.BASE_URL = (
    "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/"
    "1449138789749.ajax"
)


if __name__ == "__main__":
    raise SystemExit(probe.main())
