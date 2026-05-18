"""
Root conftest: ensures each service test package gets its own clean sys.path
by clearing the 'app' module cache between service test directories.

Without this, running multiple service suites together (e.g. llm_gateway +
llm_vetter) causes the second suite to import 'app' from the first service's
path because pytest caches the module after the first collection.
"""
import sys


def pytest_collection_modifyitems(items):
    """No-op hook — just ensures this conftest is loaded early."""


def pytest_runtest_setup(item):
    """Before each test, verify the 'app' module in sys.modules came from
    the same directory as the test file. If not, clear it so the correct
    service's conftest can re-insert its own path on the next import."""
    test_dir = str(item.fspath.dirpath())
    app_mod = sys.modules.get("app")
    if app_mod is not None:
        app_file = getattr(app_mod, "__file__", "") or ""
        if app_file and test_dir not in app_file:
            for key in list(sys.modules.keys()):
                if key == "app" or key.startswith("app."):
                    del sys.modules[key]
