import sys
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

# Clear any cached 'app' module from other service tests before adding backtester to the path
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]

sys.path.insert(0, os.path.join(ROOT, "shared"))
sys.path.insert(0, os.path.join(ROOT, "services", "backtester"))

# Legacy reporting regression names remain useful fixtures. Bind them to the
# centralized public Production finalizer used by the corrected runtime so the
# tests exercise the executable reporting implementation, not a retired copy.
try:
    import backtester.run_ldrc_nonpit_vs_pit_certified as _reporting
    from backtester import production_public_reporting as _public_reporting

    _reporting._public_production_daily = _public_reporting.public_production_daily
    _reporting._public_production_metrics = _public_reporting.public_production_metrics
    _reporting._public_metric_summary = _public_reporting.public_metric_summary
    _reporting._write_final_comparison = (
        lambda: _public_reporting.write_final_comparison(_reporting)
    )
except Exception:
    # Some focused tests intentionally import before the pinned production
    # checkout/runtime is available. Their own imports will surface any real
    # dependency error; do not make collection depend on this compatibility bind.
    pass
