import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Isolate this service's `app` package from other services' `app` packages.
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "theme-classifier"))
