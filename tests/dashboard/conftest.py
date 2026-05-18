import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DASHBOARD_PATH = os.path.join(ROOT, "services", "dashboard")

for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, _DASHBOARD_PATH)


def pytest_runtest_setup(item):
    """Re-clear and re-insert dashboard path before each test in this suite."""
    if str(item.fspath).startswith(os.path.dirname(__file__)):
        for key in list(sys.modules.keys()):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        if _DASHBOARD_PATH not in sys.path:
            sys.path.insert(0, _DASHBOARD_PATH)
