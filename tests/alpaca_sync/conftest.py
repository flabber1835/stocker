import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Set env vars BEFORE the app module is imported so module-level constants
# pick up known values. ALPACA_API_KEY=demo disables auto-sync on startup.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("ALPACA_API_KEY", "demo")
os.environ.setdefault("ALPACA_SECRET_KEY", "demo")

# Clear any cached 'app' module from other service tests before adding
# alpaca-sync to the path.
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "alpaca-sync"))
