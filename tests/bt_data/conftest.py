import os, sys
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
os.environ.setdefault(
    "BT_DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/bt_test")
# bt-data is self-contained; add its app to the path. Clear any other service's
# 'app' binding first (the cross-service package-name collision pattern).
for key in list(sys.modules.keys()):
    if key == "app" or key.startswith("app."):
        del sys.modules[key]
sys.path.insert(0, os.path.join(ROOT, "services", "bt-data"))
