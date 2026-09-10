"""Regression coverage for the direct automation Compose argument boundary."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
WRAPPER = ROOT / "scripts" / "sentinel-automation-compose.sh"
ENVELOPE = ROOT / "scripts" / "sentinel_execution_envelope.py"


class AutomationComposeArgumentBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copyfile(WRAPPER, scripts / WRAPPER.name)
        shutil.copyfile(ENVELOPE, scripts / ENVELOPE.name)
        (scripts / "sentinel_host_python.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8")
        (scripts / "sentinel-env.sh").write_text(
            "sentinel_load_environment() { printf 'preflight\\n' >> effects; return 0; }\n",
            encoding="utf-8")
        binary = self.root / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text(
            "#!" + sys.executable + "\n"
            "from pathlib import Path\n"
            "Path('docker-ran').write_text('yes', encoding='utf-8')\n"
            "raise SystemExit(93)\n",
            encoding="utf-8")
        docker.chmod(0o700)
        self.process = {
            "PATH": str(binary) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "SENTINEL_HOST_PYTHON": sys.executable,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "a" * 64,
            "SENTINEL_TEST_IMAGE_DIGEST": "sha256:" + "b" * 64,
            "SENTINEL_GIT_COMMIT": "c" * 40,
        }

    def run_wrapper(self, *arguments, extra_env=None):
        env = dict(self.process)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", "scripts/sentinel-automation-compose.sh", *arguments],
            cwd=str(self.root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=10)

    def assert_refused_before_docker(self, *arguments, extra_env=None):
        marker = self.root / "docker-ran"
        marker.unlink(missing_ok=True)
        result = self.run_wrapper(*arguments, extra_env=extra_env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("REFUSED", result.stderr)
        self.assertFalse(marker.exists(), result.stderr)
        self.assertTrue((self.root / "effects").exists())

    def test_explicit_env_file_cannot_replace_validated_interpolation(self):
        for arguments in (
                ("--env-file", "other.env", "up", "-d"),
                ("--env-file=other.env", "up", "-d"),
                ("--ansi", "never", "--env-file", "other.env", "up")):
            with self.subTest(arguments=arguments):
                self.assert_refused_before_docker(*arguments)

    def test_extra_compose_file_cannot_replace_validated_service_graph(self):
        for arguments in (
                ("-f", "other.yml", "up", "-d"),
                ("-fother.yml", "up", "-d"),
                ("--file", "other.yml", "up", "-d"),
                ("--file=other.yml", "up", "-d")):
            with self.subTest(arguments=arguments):
                self.assert_refused_before_docker(*arguments)

    def test_project_identity_and_directory_are_fixed(self):
        for arguments in (
                ("--project-name", "sentinel-test", "config"),
                ("--project-name=sentinel-test", "ps"),
                ("-psentinel-test", "logs"),
                ("--project-directory", "/synthetic/project", "logs"),
                ("--project-directory=/synthetic/project", "config")):
            with self.subTest(arguments=arguments):
                self.assert_refused_before_docker(*arguments)

    def test_only_the_fixed_automation_profile_may_be_forwarded(self):
        for arguments in (
                ("--profile", "shadow", "up"),
                ("--profile=authorized-cli", "up"),
                ("--profile", "automation", "--profile", "shadow", "up")):
            with self.subTest(arguments=arguments):
                self.assert_refused_before_docker(*arguments)

        for arguments in (
                ("--profile", "automation", "ps"),
                ("--profile=automation", "up", "-d")):
            with self.subTest(arguments=arguments):
                marker = self.root / "docker-ran"
                marker.unlink(missing_ok=True)
                result = self.run_wrapper(*arguments)
                self.assertEqual(result.returncode, 93, result.stderr)
                self.assertTrue(marker.exists(), result.stderr)

    def test_ambient_docker_and_compose_selectors_are_refused(self):
        for key, value in (
                ("COMPOSE_PROFILES", "shadow"),
                ("COMPOSE_PROJECT_NAME", "sentinel-test"),
                ("COMPOSE_FILE", "other.yml"),
                ("DOCKER_HOST", "tcp://127.0.0.1:2375"),
                ("DOCKER_CONTEXT", "remote"),
                ("DOCKER_CONFIG", "/tmp/other-docker")):
            with self.subTest(key=key):
                self.assert_refused_before_docker("up", "-d", extra_env={key: value})

    def test_run_execution_model_overrides_are_refused(self):
        for arguments in (
                ("run", "-e", "SENTINEL_AUTOMATION_LEASE_SECONDS=3", "sentinel-automation"),
                ("run", "--env-from-file", "other.env", "sentinel-automation"),
                ("run", "--entrypoint", "sh", "sentinel-automation"),
                ("run", "-v", "/tmp:/var/lib/sentinel", "sentinel-automation"),
                ("run", "--user", "0", "sentinel-automation")):
            with self.subTest(arguments=arguments):
                self.assert_refused_before_docker(*arguments)

    def test_destructive_volume_removal_is_refused(self):
        for arguments in (
                ("down", "-v"), ("down", "--volumes"),
                ("down", "--remove-orphans"), ("down", "--rmi", "all"),
                ("rm", "-v", "sentinel-automation")):
            with self.subTest(arguments=arguments):
                self.assert_refused_before_docker(*arguments)

    def test_benign_options_and_application_arguments_still_reach_compose(self):
        cases = (
            ("--ansi", "never", "--progress=plain", "ps"),
            ("run", "--rm", "sentinel-automation", "--", "--profile", "application-value"),
            ("up", "-d", "--no-deps", "--force-recreate", "sentinel-automation"),
            ("stop", "sentinel-automation"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                marker = self.root / "docker-ran"
                marker.unlink(missing_ok=True)
                result = self.run_wrapper(*arguments)
                self.assertEqual(result.returncode, 93, result.stderr)
                self.assertTrue(marker.exists(), result.stderr)


if __name__ == "__main__":
    unittest.main()
