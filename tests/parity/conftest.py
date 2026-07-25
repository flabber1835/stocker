"""Backtester's `app` package — this suite exercises config-replay's composer
against the manifest that describes it. The bt-engine side is covered in
tests/bt_engine/ because the two services' `app` packages collide in one
process (the standing cross-service pattern; scripts/run-tests.sh runs each
suite separately)."""
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "backtester"))
