"""Protected policy preflight remains literal, bounded and Python 3.8 compatible."""
from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import unittest

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", str(Path(__file__).resolve().parents[2])))
SPEC = importlib.util.spec_from_file_location("protected_host_env", ROOT / "scripts/sentinel_env.py")
env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(env)


class ProtectedPolicyHostTests(unittest.TestCase):
    def test_empty_legacy_environment_remains_valid(self):
        for values in ({}, {"SENTINEL_PAPER_BUY_POLICY": "", "SENTINEL_PAPER_BUY_CAP_BPS": ""}):
            with self.subTest(values=values):
                env._validate_semantics(values, alert_dispatcher=False)

    def test_explicit_canonical_cap_accepts_reviewed_boundaries(self):
        for cap in ("0", "100", "500"):
            with self.subTest(cap=cap):
                env._validate_semantics({"SENTINEL_PAPER_BUY_POLICY": "PROTECTED_LIMIT_DAY_V1",
                                         "SENTINEL_PAPER_BUY_CAP_BPS": cap}, alert_dispatcher=False)

    def test_missing_and_noncanonical_caps_refuse(self):
        for cap in ("", "-1", "+1", "01", "1.5", "501", "1000", "NaN", "1" * 10000):
            with self.subTest(cap=cap[:12]):
                with self.assertRaisesRegex(env.EnvRefused, "INVALID_PAPER_BUY_CAP_BPS"):
                    env._validate_semantics({"SENTINEL_PAPER_BUY_POLICY": "PROTECTED_LIMIT_DAY_V1",
                                             "SENTINEL_PAPER_BUY_CAP_BPS": cap}, alert_dispatcher=False)

    def test_unknown_or_orphan_policy_refuses(self):
        with self.assertRaisesRegex(env.EnvRefused, "INVALID_PAPER_BUY_POLICY"):
            env._validate_semantics({"SENTINEL_PAPER_BUY_POLICY": "other"}, alert_dispatcher=False)
        with self.assertRaisesRegex(env.EnvRefused, "PAPER_BUY_POLICY_REQUIRED"):
            env._validate_semantics({"SENTINEL_PAPER_BUY_CAP_BPS": "100"}, alert_dispatcher=False)

    def test_changed_host_module_parses_as_python38(self):
        ast.parse((ROOT / "scripts/sentinel_env.py").read_text(encoding="utf-8"),
                  filename="scripts/sentinel_env.py", feature_version=8)
