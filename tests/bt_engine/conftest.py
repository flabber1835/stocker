import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Clear any cached 'app' module from other service tests before adding bt-engine
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

if os.environ.get("BT_ENGINE_IN_IMAGE") == "1":
    # The test lens is layered on the built production image.  Repository
    # sources exist under /work/repo for inspection only and must never shadow
    # the executable /app/app package being certified.
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(ROOT, "shared"))
    sys.path.insert(0, os.path.join(ROOT, "services", "bt-engine"))
