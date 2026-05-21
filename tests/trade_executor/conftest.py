import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Set env vars BEFORE the app module is imported so module-level constants
# pick up known values.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("ALPACA_API_KEY", "")
os.environ.setdefault("ALPACA_SECRET_KEY", "")
os.environ.setdefault("RISK_SERVICE_URL", "http://risk-service-mock")
os.environ.setdefault("EXIT_SYNC_MAX_AGE_HOURS", "24")
os.environ.setdefault("DEFAULT_MAX_POSITIONS", "30")

# Clear any cached 'app' module from other service tests before adding
# trade-executor to the path.
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "trade-executor"))
