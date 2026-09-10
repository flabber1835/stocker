"""Isolated harness: no broker credentials and no production services."""
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", HERE.parents[1]))
sys.path.insert(0, str(HERE))
# In the CI lens, retain the source-matched runtime import from /app.
if not os.environ.get("SENTINEL_IN_IMAGE"):
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith(("ALPACA_", "APCA_", "SENTINEL_")) and key not in {
            "SENTINEL_REPO_ROOT", "SENTINEL_IN_IMAGE",
        }:
            monkeypatch.delenv(key)
