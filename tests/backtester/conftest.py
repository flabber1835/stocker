import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Clear any cached 'app' module from other service tests before adding backtester to the path
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "backtester"))


def pytest_collection_modifyitems(session, config, items):
    """Bind legacy reporting test names to the executable public finalizer.

    The reporting module imports the pinned Production runtime and is therefore
    loaded by its own test module during collection. Bind after collection so
    this fixture never changes dependency/import order.
    """
    reporting = sys.modules.get("backtester.run_ldrc_nonpit_vs_pit_certified")
    if reporting is None:
        return
    from backtester import production_public_reporting as public_reporting

    reporting._public_production_daily = public_reporting.public_production_daily
    reporting._public_production_metrics = public_reporting.public_production_metrics
    reporting._public_metric_summary = public_reporting.public_metric_summary
    reporting._write_final_comparison = (
        lambda: public_reporting.write_final_comparison(reporting)
    )
