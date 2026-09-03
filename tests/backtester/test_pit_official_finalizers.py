from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
OFFICIAL = (
    WORKFLOWS / "backtester-production-strict-pit-20y.yml",
    WORKFLOWS / "backtester-research-only-20y.yml",
)


class OfficialPITFinalizerStructureTests(unittest.TestCase):
    def test_official_finalizers_reacquire_and_verify_digest_pinned_dataset(self) -> None:
        for path in OFFICIAL:
            text = path.read_text(encoding="utf-8")
            self.assertIn("PIT_OFFICIAL_BACKTEST: '1'", text, path.name)
            self.assertIn("backtester-pit-certification-suite.yml", text, path.name)
            self.assertIn("id: dataset", text, path.name)
            self.assertIn('test "${PACKAGE#*@sha256:}" != "${PACKAGE}"', text, path.name)
            self.assertIn('docker create "${PACKAGE}" /bin/true', text, path.name)
            self.assertIn("canonical_pit_package.py verify", text, path.name)
            self.assertIn("DATASET_JOB_RESULT", text, path.name)
            self.assertIn(
                'if test "${DATASET_JOB_RESULT}" = success && test -d "${PIT_DATASET}"',
                text,
                path.name,
            )
            self.assertRegex(
                text,
                r"certify_backtest_result(?:_v2)?\.py finalize",
                path.name,
            )

    def test_official_finalizers_have_one_authoritative_pit_conclusion(self) -> None:
        for path in OFFICIAL:
            text = path.read_text(encoding="utf-8")
            self.assertEqual(
                text.count("Enforce authoritative certification conclusion"), 1, path.name
            )
            self.assertEqual(text.count("PIT CERTIFIED — point-in-time"), 1, path.name)


if __name__ == "__main__":
    unittest.main()
