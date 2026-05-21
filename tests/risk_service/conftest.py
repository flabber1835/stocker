import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Set env vars BEFORE the app module is imported so module-level constants
# pick up known values.
os.environ.setdefault("KILL_SWITCH", "false")
os.environ.setdefault("LIVE_TRADING_ENABLED", "false")
os.environ.setdefault("MAX_ORDER_NOTIONAL", "50000.0")
os.environ.setdefault("PAPER_ONLY", "true")

# Clear any cached 'app' module from other service tests before adding
# risk-service to the path.
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "risk-service"))
