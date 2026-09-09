import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "shared")]


def pytest_configure(config):
    config.addinivalue_line("markers", "postgres: requires disposable loopback PostgreSQL")
