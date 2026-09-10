"""Deterministic concurrency regression for managed Sentinel .env persistence."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_writer():
    path = SCRIPTS / "sentinel_env_writer.py"
    spec = importlib.util.spec_from_file_location("sentinel_env_writer_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class EnvWriterSerialization(unittest.TestCase):
    def test_supported_managed_writers_are_serialized(self):
        writer = _load_writer()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            path.write_text("BASE=1\n", encoding="utf-8")
            first_ready = threading.Event()
            release_first = threading.Event()
            second_reached_commit = threading.Event()
            failures = []

            def first_callback():
                first_ready.set()
                if not release_first.wait(5):
                    raise RuntimeError("test release timed out")

            def second_callback():
                second_reached_commit.set()

            def run(updates, callback):
                try:
                    writer.safe_update_dotenv(path, updates, before_commit=callback)
                except Exception as exc:  # surfaced after both threads are joined
                    failures.append(exc)

            first = threading.Thread(target=run, args=({"FIRST": "1"}, first_callback))
            second = threading.Thread(target=run, args=({"SECOND": "1"}, second_callback))
            first.start()
            self.assertTrue(first_ready.wait(2))
            second.start()
            time.sleep(0.15)
            self.assertFalse(
                second_reached_commit.is_set(),
                "second managed writer crossed the commit boundary while the first held it")
            release_first.set()
            first.join(5)
            second.join(5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(failures, [])
            text = path.read_text(encoding="utf-8")
            self.assertIn("FIRST=1", text)
            self.assertIn("SECOND=1", text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual((path.parent / ".env.deploy-safe.lock").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
