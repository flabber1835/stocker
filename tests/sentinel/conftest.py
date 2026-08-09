"""Put this directory on sys.path so the suites share one `fakes` module.

`tests/` has no `__init__.py`, so these are not importable as a package — and a
`tests/sentinel/__init__.py` must NOT be added to fix that: it would make
`import sentinel` resolve to the TEST package and shadow the real one, which is
exactly how this suite first failed to collect.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(HERE), str(ROOT), str(ROOT / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)
