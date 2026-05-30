import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Set env BEFORE importing the app so module-level constants pick up safe values.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

# Clear any cached 'app' module from other service test packages before adding
# alpaca-sim to the path (each service ships its own top-level `app` package).
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "alpaca-sim"))
