"""Independent contract tests for the Sentinel Docker/Compose authority envelope."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
ENV_BRIDGE = SCRIPTS / "sentinel-env.sh"


class ExecutionEnvelope(unittest.TestCase):
    def run_environment(self, extra_env=None):
        process = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        if extra_env:
            process.update(extra_env)
        return subprocess.run(
            ["bash", "-c",
             '. "$1"; PYTHON="$2"; sentinel_require_execution_environment',
             "sentinel-envelope-test", str(ENV_BRIDGE), sys.executable],
            cwd=str(ROOT), env=process, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=10)

    def run_compose(self, surface, *arguments):
        return subprocess.run(
            ["bash", "-c",
             '. "$1"; PYTHON="$2"; shift 2; sentinel_require_compose_envelope "$@"',
             "sentinel-envelope-test", str(ENV_BRIDGE), sys.executable,
             surface, *arguments],
            cwd=str(ROOT), env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)

    def assert_compose_refused(self, surface, *arguments):
        result = self.run_compose(surface, *arguments)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("REFUSED", result.stderr)

    def test_environment_rejects_all_authority_selectors(self):
        cases = (
            ("COMPOSE_PROJECT_NAME", "other"),
            ("COMPOSE_FILE", "other.yml"),
            ("COMPOSE_PROFILES", "shadow"),
            ("COMPOSE_PATH_SEPARATOR", ";"),
            ("COMPOSE_ENV_FILES", "other.env"),
            ("COMPOSE_DISABLE_ENV_FILE", "0"),
            ("DOCKER_HOST", "tcp://127.0.0.1:2375"),
            ("DOCKER_CONTEXT", "remote"),
            ("DOCKER_CONFIG", "/tmp/docker"),
            ("DOCKER_CERT_PATH", "/tmp/certs"),
            ("DOCKER_TLS_VERIFY", "1"),
            ("DOCKER_API_VERSION", "1.40"),
            ("DOCKER_DEFAULT_PLATFORM", "linux/arm64"),
            ("BUILDKIT_HOST", "tcp://builder:1234"),
            ("BUILDX_BUILDER", "remote"),
        )
        for key, value in cases:
            with self.subTest(key=key):
                result = self.run_environment({key: value})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(key if key != "DOCKER_CONTEXT" else "Docker context",
                              result.stderr)

    def test_environment_accepts_only_canonical_runtime_controls(self):
        result = self.run_environment({
            "DOCKER_CONTEXT": "default",
            "COMPOSE_DISABLE_ENV_FILE": "1",
            "COMPOSE_ENV_FILES": "/dev/null",
        })
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_operational_global_graph_escapes_are_refused(self):
        cases = (
            ("--profile", "cli", "run", "sentinel", "status"),
            ("--env-file", "other.env", "up"),
            ("-f", "other.yml", "up"),
            ("-fother.yml", "restart"),
            ("-p", "other", "stop"),
            ("-pother", "up"),
            ("--project-name=other", "kill"),
            ("--project-directory=/tmp", "up"),
            ("--compatibility", "up"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assert_compose_refused("base", *arguments)

    def test_read_only_inspection_has_no_operational_authority(self):
        cases = (
            ("--env-file", "other.env", "config"),
            ("-fother.yml", "config"),
            ("--project-name=other", "ps"),
            ("--project-directory=/tmp", "logs"),
            ("--profile", "shadow", "config"),
            ("--compatibility", "images"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_compose("automation", *arguments)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_run_execution_overrides_are_refused(self):
        options = (
            ("-e", "A=B"), ("--env", "A=B"),
            ("--env-from-file", "other.env"),
            ("--entrypoint", "sh"), ("-v", "/tmp:/x"),
            ("--volume", "/tmp:/x"), ("-u", "0"), ("--user", "0"),
            ("--name", "other"), ("-p", "1234:1234"),
            ("--publish", "1234:1234"), ("--workdir", "/tmp"),
            ("--cap-add", "ALL"), ("--cap-drop", "ALL"),
            ("--pull", "always"),
        )
        for option, value in options:
            with self.subTest(option=option):
                self.assert_compose_refused(
                    "automation", "run", option, value, "sentinel-automation")

    def test_run_service_selection_is_fixed(self):
        cases = (
            ("base", "sentinel-postgres"),
            ("base", "sentinel-panel"),
            ("automation", "sentinel-postgres"),
            ("automation", "sentinel-authorized-cli"),
            ("automation", "sentinel-authority-permissions"),
            ("automation", "sentinel-shadow"),
        )
        for surface, service in cases:
            with self.subTest(surface=surface, service=service):
                self.assert_compose_refused(surface, "run", "--rm", service, "status")

    def test_application_arguments_begin_after_service(self):
        result = self.run_compose(
            "automation", "run", "--rm", "-T", "--no-deps",
            "sentinel-automation", "--", "--profile", "application-value",
            "-e", "application-value")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_destructive_and_future_operational_options_are_refused(self):
        cases = (
            ("down", "-v"), ("down", "--volumes"),
            ("down", "--remove-orphans"), ("down", "--rmi=all"),
            ("rm", "--volumes", "sentinel"),
            ("wait", "--down-project", "sentinel-postgres"),
            ("up", "--future-dangerous-option", "sentinel-panel"),
            ("down", "--future-dangerous-option"),
            ("stop", "--signal", "HUP", "sentinel-automation"),
            ("kill", "--signal", "HUP", "sentinel-automation"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assert_compose_refused("automation", *arguments)

    def test_startup_identity_changing_flags_are_refused(self):
        cases = (
            ("up", "--build"), ("up", "--pull", "always"),
            ("up", "--remove-orphans"), ("up", "--renew-anon-volumes"),
            ("up", "--scale", "sentinel-automation=2"),
            ("up", "--no-recreate", "sentinel-automation"),
            ("up", "--watch", "sentinel-automation"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assert_compose_refused("automation", *arguments)

    def test_stale_container_transitions_and_exec_are_refused(self):
        for command in ("start", "restart", "unpause", "pause"):
            with self.subTest(command=command):
                self.assert_compose_refused("automation", command, "sentinel-automation")
                self.assert_compose_refused("base", command, "sentinel-postgres")
        self.assert_compose_refused(
            "automation", "exec", "sentinel-automation", "python", "-c", "pass")
        self.assert_compose_refused(
            "base", "exec", "sentinel-postgres", "psql", "-U", "sentinel")

    def test_startup_service_allowlist_blocks_profile_activation(self):
        cases = (
            ("base", "sentinel"),
            ("base", "sentinel-automation"),
            ("automation", "sentinel-authorized-cli"),
            ("automation", "sentinel-authority-permissions"),
            ("automation", "sentinel-shadow"),
            ("automation", "unknown-service"),
        )
        for surface, service in cases:
            with self.subTest(surface=surface, service=service):
                self.assert_compose_refused(surface, "up", "-d", service)
                self.assert_compose_refused(surface, "create", service)

    def test_explicit_automation_start_requires_dispatcher_pair(self):
        self.assert_compose_refused(
            "automation", "up", "-d", "sentinel-automation")
        result = self.run_compose(
            "automation", "up", "-d", "sentinel-automation",
            "sentinel-alert-dispatcher")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_supported_fixed_operations_pass(self):
        cases = (
            ("automation", ("--profile", "automation", "ps")),
            ("automation", ("--ansi", "never", "--progress=plain", "logs")),
            ("automation", ("up", "-d", "--no-deps", "--force-recreate",
                            "sentinel-automation", "sentinel-alert-dispatcher")),
            ("automation", ("down", "--timeout", "30")),
            ("automation", ("rm", "--force", "sentinel-automation")),
            ("automation", ("wait", "sentinel-automation")),
            ("base", ("run", "--rm", "-T", "sentinel", "status")),
            ("base", ("up", "-d", "--no-deps", "--force-recreate", "sentinel-panel")),
            ("base", ("ps", "-q", "sentinel-panel")),
            ("base", ("stop", "--timeout", "30", "sentinel-postgres")),
        )
        for surface, arguments in cases:
            with self.subTest(surface=surface, arguments=arguments):
                result = self.run_compose(surface, *arguments)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrappers_bind_guard_project_and_context(self):
        base = (SCRIPTS / "sentinel-compose.sh").read_text(encoding="utf-8")
        automation = (SCRIPTS / "sentinel-automation-compose.sh").read_text(encoding="utf-8")
        env_bridge = ENV_BRIDGE.read_text(encoding="utf-8")
        emergency = (SCRIPTS / "sentinel-emergency-kill.sh").read_text(encoding="utf-8")
        volume = (SCRIPTS / "sentinel-state-volume-permissions.sh").read_text(encoding="utf-8")

        self.assertIn('sentinel_require_compose_envelope base "$@"', base)
        self.assertIn('sentinel_require_compose_envelope automation "$@"', automation)
        self.assertIn("--project-name sentinel", base)
        self.assertIn("--project-name sentinel", automation)
        self.assertIn("docker --context default compose", base)
        self.assertIn("docker --context default compose", automation)
        self.assertIn("sentinel_require_execution_environment", env_bridge)
        self.assertIn("export DOCKER_CONTEXT=default", env_bridge)
        self.assertIn("docker --context default ps -q", emergency)
        self.assertIn("docker --context default exec -i", emergency)
        self.assertNotIn("docker compose", emergency)
        self.assertNotIn("SENTINEL_RUNTIME_IMAGE_REF", emergency)
        self.assertIn("docker --context default volume inspect", volume)
        self.assertIn("docker --context default run", volume)


if __name__ == "__main__":
    unittest.main()
