#!/usr/bin/env python3
"""Schema-v2 certification with the complete Champion source dependency set."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester import certify_backtest_result_v2 as v2

current = list(v2.implementation.OFFICIAL_SOURCE_FILES['research'])
for member in ('backtester', 'research/strategy9-e3-broad-stability'):
    if member not in current:
        current.append(member)
v2.implementation.OFFICIAL_SOURCE_FILES['research'] = tuple(current)

if __name__ == '__main__':
    raise SystemExit(v2.main())
