"""Prove the fixture-producer acceptance detects missing or premature selection."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "shared")]

from tools.sentinel_rolling_storage_falsifiers import child

TEST = "tests/internal_state/test_physical.py"
MUTANTS = {
    "physical_publication_removed": ("tests.internal_state.physical",
        "self._publish_selection(base, system_id)", "pass",
        "test_checkpoint_selects_only_verified_archived_media[pg_verifybackup]"),
    "physical_publication_before_verification": ("tests.internal_state.physical",
        'self.command("pg_verifybackup", base, timeout=60)',
        'self._publish_selection(base, self.sql("SELECT system_identifier::text FROM pg_control_system()")[0])\n'
        '        self.command("pg_verifybackup", base, timeout=60)',
        "test_checkpoint_selects_only_verified_archived_media[pg_verifybackup]"),
    "physical_publication_before_archive": ("tests.internal_state.physical",
        'self.wait_archive(wal)\n        metadata =',
        'self._publish_selection(base, system_id)\n        self.wait_archive(wal)\n        metadata =',
        "test_checkpoint_selects_only_verified_archived_media[wait_archive]"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=(*MUTANTS, "composition_publication_removed"))
    args = parser.parse_args()
    if args.child == "composition_publication_removed":
        import pytest
        if ROOT != Path("/tmp/repo"):
            raise RuntimeError("test-source mutation requires the disposable /tmp/repo copy")
        source = ROOT / "tests/production_composition/test_canonical_go_e2e_harness.py"
        original = source.read_bytes()
        assert original.count(b"if publish_selection:") == 1
        try:
            source.write_bytes(original.replace(b"if publish_selection:", b"if False:"))
            return pytest.main([str(source) +
                "::test_bootstrapped_fixture_leaves_a_bounded_real_backup_authority[selected]",
                "-q", "-p", "no:cacheprovider"])
        finally:
            source.write_bytes(original)
    if args.child:
        return child(args.child, mutants=MUTANTS, test_file=TEST)
    failures = []
    for name in (*MUTANTS, "composition_publication_removed"):
        result = subprocess.run([sys.executable, __file__, "--child", name],
            capture_output=True, text=True)
        killed = result.returncode == 1 and "1 failed" in result.stdout
        print(name + (": KILLED" if killed else ": NOT PROVED"), flush=True)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        if not killed:
            failures.append(name)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
