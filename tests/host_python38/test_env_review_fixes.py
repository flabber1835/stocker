"""Regression tests for PR346 review fixes on the minimum host Python."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_env as env
import sentinel_env_writer as writer


BASE_SHADOW = {
    "SENTINEL_POSTGRES_PASSWORD": "synthetic-database-password",
    "SHARADAR_API_KEY": "synthetic-sharadar-key",
    "SENTINEL_BACKUP_DIR": "/synthetic/external/backup",
}


class EnvReviewFixes(unittest.TestCase):
    def test_install_shadow_is_broker_free_but_dual_is_not(self):
        env.validate(BASE_SHADOW, profile="install", target="SHADOW")
        with self.assertRaisesRegex(env.EnvRefused, "ALPACA_API_KEY"):
            env.validate(
                BASE_SHADOW, profile="install",
                target="DUAL_RUN_OBSERVATION")

    def test_launcher_shadow_reaches_bootstrap_with_no_alpaca_variables(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in (
                    "sentinel-autonomous-deploy.sh",
                    "sentinel-env.sh",
                    "sentinel_env.py"):
                shutil.copyfile(SCRIPTS / name, scripts / name)
            (scripts / "sentinel_host_python.py").write_text(
                "raise SystemExit(0)\n", encoding="utf-8")
            marker = root / "bootstrap-ran"
            (scripts / "sentinel_deployment_bootstrap.py").write_text(
                "from pathlib import Path\n"
                "Path(%r).write_text('ran', encoding='utf-8')\n"
                "raise SystemExit(77)\n" % str(marker),
                encoding="utf-8")
            for name in (
                    "sentinel-state-volume-permissions.sh",
                    "sentinel_autonomous_deploy_entry.py"):
                (scripts / name).write_text(
                    "#!/bin/sh\nexit 88\n" if name.endswith(".sh")
                    else "raise SystemExit(88)\n",
                    encoding="utf-8")

            (root / ".env").write_text(
                "SENTINEL_POSTGRES_PASSWORD=synthetic-database-password\n"
                "SHARADAR_API_KEY=synthetic-sharadar-key\n"
                "SENTINEL_BACKUP_DIR=/synthetic/external/backup\n",
                encoding="utf-8")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            git_marker = root / "git-ran"
            git = fake_bin / "git"
            git.write_text(
                "#!/bin/sh\n"
                "touch " + str(git_marker) + "\n"
                "case \"$1\" in\n"
                "  symbolic-ref) echo main ;;\n"
                "  status) : ;;\n"
                "  rev-parse) printf '%040d\\n' 0 ;;\n"
                "  pull) : ;;\n"
                "  *) exit 91 ;;\n"
                "esac\n",
                encoding="utf-8")
            git.chmod(0o755)

            lock = tempfile.TemporaryFile()
            self.addCleanup(lock.close)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.set_inheritable(lock.fileno(), True)
            process = {
                "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                "SENTINEL_HOST_PYTHON": sys.executable,
                "SENTINEL_DEPLOY_LOCK_FD": str(lock.fileno()),
            }
            result = subprocess.run(
                ["bash", str(scripts / "sentinel-autonomous-deploy.sh"),
                 "--mode", "shadow"],
                cwd=str(root), env=process, pass_fds=(lock.fileno(),),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=10)
            self.assertEqual(result.returncode, 77, result.stderr)
            self.assertTrue(marker.exists(), result.stderr)

            marker.unlink()
            dual = subprocess.run(
                ["bash", str(scripts / "sentinel-autonomous-deploy.sh"),
                 "--mode", "dual"],
                cwd=str(root), env=process, pass_fds=(lock.fileno(),),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=10)
            self.assertEqual(dual.returncode, 2)
            self.assertIn("ALPACA_API_KEY", dual.stderr)
            self.assertFalse(marker.exists())

            for suffix, value in (
                    ("LEASE_SECONDS", "3"), ("HEARTBEAT_SECONDS", "12"),
                    ("RETRY_BASE_SECONDS", "901"), ("RETRY_MAX_SECONDS", "4"),
                    ("CALLBACK_DEADLINE_SECONDS", "2")):
                with self.subTest(setting=suffix):
                    git_marker.unlink(missing_ok=True)
                    values = dict(BASE_SHADOW)
                    values["SENTINEL_AUTOMATION_" + suffix] = value
                    (root / ".env").write_text(
                        "".join(key + "=" + value + "\n" for key, value in values.items()),
                        encoding="utf-8")
                    result = subprocess.run(
                        ["bash", str(scripts / "sentinel-autonomous-deploy.sh"),
                         "--mode", "shadow"],
                        cwd=str(root), env=process, pass_fds=(lock.fileno(),),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        timeout=10)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("AUTOMATION_", result.stderr)
                    self.assertFalse(git_marker.exists())
                    self.assertFalse(marker.exists())

    def test_every_typed_runtime_family_refuses_malformed_values(self):
        invalid = {
            "SENTINEL_MAX_CYCLES": "not-an-int",
            "SENTINEL_POLL_SECONDS": "not-a-number",
            "SENTINEL_BACKUP_MAX_AGE_HOURS": "1.5",
            "SENTINEL_SHADOW_OBSERVATION_ENABLED": "maybe",
            "SENTINEL_SHADOW_OBSERVATION_ID": "bad id",
            "SENTINEL_SHADOW_STARTING_CASH": "NaN",
            "SENTINEL_SHADOW_POLL_SECONDS": "4",
            "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS": "7201",
            "SENTINEL_SHADOW_FAILURE_THRESHOLD": "0",
            "SENTINEL_REVIEWED_DEPLOYMENT_MODE": "mystery",
            "SENTINEL_AUTOMATION_PUBLICATION_DELAY_SECONDS": "x",
            "SENTINEL_AUTOMATION_EXECUTION_DELAY_SECONDS": "x",
            "SENTINEL_AUTOMATION_LEASE_SECONDS": "2",
            "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": "x",
            "SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS": "x",
            "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS": "0",
            "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS": "0",
            "SENTINEL_AUTOMATION_RETRY_MAX_SECONDS": "0",
            "SENTINEL_AUTOMATION_REFRESH_MAX_ATTEMPTS": "0",
            "SENTINEL_AUTOMATION_PREFLIGHT_RECOVER_MAX_ATTEMPTS": "0",
            "SENTINEL_AUTOMATION_PREPARE_MAX_ATTEMPTS": "0",
            "SENTINEL_AUTOMATION_EXECUTE_MAX_ATTEMPTS": "0",
            "SENTINEL_AUTOMATION_RECOVER_MAX_ATTEMPTS": "0",
            "SENTINEL_AUTOMATION_ALERT_CLAIM_SECONDS": "2",
            "SENTINEL_AUTOMATION_ALERT_MAX_ATTEMPTS": "0",
            "SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS": "nan",
            "SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS": "-1",
            "SENTINEL_AUTOMATION_ALERT_WEBHOOK_TIMEOUT_SECONDS": "31",
            "SENTINEL_AUTOMATION_ALERT_POLL_SECONDS": "61",
            "SENTINEL_AUTOMATION_ALERT_PROBE_SECONDS": "3601",
            "SENTINEL_AUTOMATION_ALERT_MAX_CONSECUTIVE_FAILURES": "0",
            "SENTINEL_AUTOMATION_ALERT_HEALTH_MAX_AGE_SECONDS": "0",
            "SENTINEL_AUTOMATION_ALERT_STARTUP_GRACE_SECONDS": "0",
            "SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS": "1801",
            "SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS": "29",
            "SENTINEL_DEPLOY_DATA_RETRY_SECONDS": "29",
            "SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS": "299",
            "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE": "0.50",
        }
        for key, value in invalid.items():
            with self.subTest(key=key, value=value):
                candidate = dict(BASE_SHADOW)
                candidate[key] = value
                with self.assertRaises(env.EnvRefused):
                    env.validate(
                        candidate, profile="install", target="SHADOW")

    def test_cross_field_runtime_invariants_refuse_before_install(self):
        cases = (
            {
                "SENTINEL_AUTOMATION_LEASE_SECONDS": "45",
                "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": "45",
            },
            {
                "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS": "901",
                "SENTINEL_AUTOMATION_RETRY_MAX_SECONDS": "900",
            },
            {
                "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": "10",
                "SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS": "9",
            },
        )
        for values in cases:
            with self.subTest(values=values):
                candidate = dict(BASE_SHADOW)
                candidate.update(values)
                with self.assertRaises(env.EnvRefused):
                    env.validate(
                        candidate, profile="install", target="SHADOW")

    def test_single_automation_override_refuses_conflict_with_service_default(self):
        cases = (
            ("LEASE_SECONDS", "3", "AUTOMATION_HEARTBEAT_NOT_BELOW_LEASE"),
            ("HEARTBEAT_SECONDS", "12", "AUTOMATION_HEARTBEAT_NOT_BELOW_LEASE"),
            ("RETRY_BASE_SECONDS", "901", "AUTOMATION_RETRY_RANGE_INVALID"),
            ("RETRY_MAX_SECONDS", "4", "AUTOMATION_RETRY_RANGE_INVALID"),
            ("CALLBACK_DEADLINE_SECONDS", "2", "AUTOMATION_CALLBACK_BELOW_HEARTBEAT"),
        )
        for suffix, value, reason in cases:
            with self.subTest(setting=suffix):
                candidate = dict(BASE_SHADOW)
                candidate["SENTINEL_AUTOMATION_" + suffix] = value
                with self.assertRaisesRegex(env.EnvRefused, reason):
                    env.validate(candidate, profile="install", target="SHADOW")

    def test_service_defaults_and_valid_partial_automation_overrides(self):
        cases = (
            {},
            {"SENTINEL_AUTOMATION_LEASE_SECONDS": "4"},
            {"SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": "11"},
            {"SENTINEL_AUTOMATION_RETRY_BASE_SECONDS": "900"},
            {"SENTINEL_AUTOMATION_RETRY_MAX_SECONDS": "5"},
            {"SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS": "3"},
        )
        for values in cases:
            with self.subTest(values=values):
                candidate = dict(BASE_SHADOW)
                candidate.update(values)
                try:
                    env.validate(candidate, profile="install", target="SHADOW")
                except env.EnvRefused as exc:
                    self.fail("valid effective service configuration refused: %s" % exc)

    def test_valid_runtime_edge_spellings_survive_preflight(self):
        candidate = dict(BASE_SHADOW)
        candidate.update({
            "SENTINEL_SHADOW_OBSERVATION_ENABLED": "true",
            "SENTINEL_SHADOW_POLL_SECONDS": "5",
            "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS": "30.5",
            "SENTINEL_SHADOW_FAILURE_THRESHOLD": "1",
            "SENTINEL_AUTOMATION_LEASE_SECONDS": "3",
            "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": "2",
            "SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS": "2",
            "SENTINEL_AUTOMATION_ALERT_WEBHOOK_TIMEOUT_SECONDS": "0.5",
            "SENTINEL_AUTOMATION_ALERT_POLL_SECONDS": "0.5",
            "SENTINEL_AUTOMATION_ALERT_PROBE_SECONDS": "1.5",
            "SENTINEL_AUTOMATION_ALERT_HEALTH_MAX_AGE_SECONDS": "0.5",
            "SENTINEL_AUTOMATION_ALERT_STARTUP_GRACE_SECONDS": "0.5",
        })
        env.validate(candidate, profile="install", target="SHADOW")

    def test_safe_writer_preserves_secret_mode_and_unmanaged_values(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text(
                "ALPACA_SECRET_KEY=keep-this-secret\n"
                "SENTINEL_RUNTIME_IMAGE_DIGEST=sha256:old\n",
                encoding="utf-8")
            path.chmod(0o600)
            writer.safe_update_dotenv(path, {
                "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "1" * 64,
            })
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            text = path.read_text(encoding="utf-8")
            self.assertIn("ALPACA_SECRET_KEY=keep-this-secret", text)
            self.assertIn(
                "SENTINEL_RUNTIME_IMAGE_DIGEST=sha256:" + "1" * 64, text)

    def test_safe_writer_refuses_concurrent_replacement_and_keeps_operator_edit(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text(
                "ALPACA_SECRET_KEY=original\n"
                "SENTINEL_GIT_COMMIT=" + "a" * 40 + "\n",
                encoding="utf-8")
            path.chmod(0o600)

            def concurrent_edit():
                replacement = path.with_name(".env.operator")
                replacement.write_text(
                    "ALPACA_SECRET_KEY=operator\n"
                    "SENTINEL_GIT_COMMIT=" + "b" * 40 + "\n",
                    encoding="utf-8")
                replacement.chmod(0o600)
                os.replace(str(replacement), str(path))

            with self.assertRaisesRegex(
                    writer.EnvWriteRefused, "changed after"):
                writer.safe_update_dotenv(
                    path, {"SENTINEL_GIT_COMMIT": "c" * 40},
                    before_commit=concurrent_edit)
            text = path.read_text(encoding="utf-8")
            self.assertIn("ALPACA_SECRET_KEY=operator", text)
            self.assertIn("SENTINEL_GIT_COMMIT=" + "b" * 40, text)

    def test_safe_writer_refuses_concurrent_creation(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"

            def concurrent_create():
                path.write_text(
                    "ALPACA_SECRET_KEY=operator\n", encoding="utf-8")
                path.chmod(0o600)

            with self.assertRaisesRegex(
                    writer.EnvWriteRefused, "appeared concurrently"):
                writer.safe_update_dotenv(
                    path, {"SENTINEL_GIT_COMMIT": "c" * 40},
                    before_commit=concurrent_create)
            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "ALPACA_SECRET_KEY=operator\n")

    def test_production_entry_routes_both_legacy_writers_through_safe_writer(self):
        import sentinel_autonomous_deploy_entry as entry
        original_core = entry.core.update_dotenv
        original_bootstrap = entry.bootstrap._safe_update_dotenv
        original_overlay = entry.bootstrap._install_wallclock_independent_dual_overlay
        try:
            entry.install_runtime_guards(None)
            self.assertIs(entry.core.update_dotenv, entry._deploy_writer)
            self.assertIs(
                entry.bootstrap._safe_update_dotenv, entry._deploy_writer)
        finally:
            entry.core.update_dotenv = original_core
            entry.bootstrap._safe_update_dotenv = original_bootstrap
            entry.bootstrap._install_wallclock_independent_dual_overlay = original_overlay

    def test_shadow_overlay_config_and_integrity_never_require_broker_secrets(self):
        import sentinel_autonomous_deploy_entry as entry
        original_cfg = entry.bootstrap.hardened.Config
        original_deploy = entry.bootstrap.BootstrapDeploy
        original_verify = entry.core.verify_reviewed_account_binding
        original_key = entry.bootstrap._signing_key_path
        try:
            entry._install_shadow_overlay()
            with tempfile.TemporaryDirectory() as raw:
                cfg = entry.bootstrap.hardened.Config({
                    **BASE_SHADOW,
                    "SENTINEL_RUNTIME_IMAGE_REPOSITORY":
                        "ghcr.io/example/sentinel",
                    "SENTINEL_TEST_IMAGE_REPOSITORY":
                        "ghcr.io/example/sentinel-test",
                    "SENTINEL_AUTHORITY_ARTIFACTS_DIR": raw,
                })
                self.assertEqual(cfg.account_id, "")
                self.assertEqual(cfg.deployment_id, "")
                reviewed = SimpleNamespace(mode="shadow")
                runner = SimpleNamespace(env={})
                obj = entry.bootstrap.BootstrapDeploy(
                    cfg, runner, Path(raw),
                    reviewed_validation=reviewed)
                self.assertEqual(
                    obj.check_paper_account_deployment_integrity(),
                    "BROKER_NOT_APPLICABLE")
                obj._status = lambda: {
                    "ownership": "NOT_OWNED",
                    "paper_execution_authority": {},
                    "administrative_authority": {},
                }
                status = obj.check_durable_deployment_integrity()
                self.assertEqual(status["ownership"], "NOT_OWNED")
                entry.core.verify_reviewed_account_binding(reviewed, "")
        finally:
            entry.bootstrap.hardened.Config = original_cfg
            entry.bootstrap.BootstrapDeploy = original_deploy
            entry.core.verify_reviewed_account_binding = original_verify
            entry.bootstrap._signing_key_path = original_key


if __name__ == "__main__":
    unittest.main()
