import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Clear any cached 'app' module from other service tests before adding llm-gateway to the path
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "llm-gateway"))
