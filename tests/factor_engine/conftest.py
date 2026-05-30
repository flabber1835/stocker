import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
# Test the LIVE factor math, not the archived factor-engine copy. The two had
# diverged (e.g. the momentum off-by-one fixed in the pipeline copy), so pointing
# the suite at _archive gave false confidence — it validated dead code that no
# longer matches what runs in production.
sys.path.insert(0, os.path.join(ROOT, "services", "pipeline"))
