"""Sentinel's market-data feed — Sharadar, replacing Alpha Vantage.

The retirement of AV is the point, not a side effect: Wealth Core was certified
on Sharadar, so reading Sharadar in production makes live and certification share
a price history instead of merely resembling one.

The historical ``SENTINEL_FEED_SERVICE_MODE=GO_VALIDATION`` child belonged to
the pre-phased validator. It could self-assert feed-binding environment and run
schema/feed mutation without the host GO flock, stable-certification phase, or
verified orchestration capability. That mode is retired and is refused at the
feed-package membrane so copying or renaming the old producer cannot resurrect
the bypass. The supported phased preparation deliberately removes this variable
and enters through the clean-HEAD/exact-image feed gate instead.
"""
from __future__ import annotations

import os


if os.environ.get("SENTINEL_FEED_SERVICE_MODE") == "GO_VALIDATION":
    raise RuntimeError(
        "legacy GO_VALIDATION feed mode is disabled; use the verified "
        "scripts/sentinel-go-validate.sh lifecycle")
