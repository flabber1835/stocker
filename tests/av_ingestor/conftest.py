import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Clear any cached 'app' module from other service tests before adding av-ingestor to the path
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

# Provide a dummy DATABASE_URL so the module-level guard doesn't raise on import.
# The tests only exercise pure helper functions that never touch the DB.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "av-ingestor"))
