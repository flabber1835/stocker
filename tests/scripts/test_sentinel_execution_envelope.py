"""Independent contract tests for the Sentinel Docker/Compose authority envelope."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sentinel_execution_envelope as envelope  # noqa: E402


class ExecutionEnvelope(unittest.TestCase):
    def assert_env_refused(self, key, value):
        with self.assertRaises(envelope.ExecutionEnvelopeRefused):
            envelope.validate_environment({key: value})

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
                self.assert_env_refused(key, value)

    def test_environment_accepts_only_canonical_runtime_controls(self):
        envelope.validate_environment({
            "DOCKER_CONTEXT": "default",
            "COMPOSE_DISABLE_ENV_FILE": "1",
            "COMPOSE_ENV_FILES": "/dev/null",
        })

    def test_base_rejects_every_global_graph_escape(self):
        cases = (
            ("--profile", "cli", "run", "sentinel", "status"),
            ("--env-file", "other.env", "config"),
            ("-f", "other.yml", "config"),
            ("-fother.yml", "config"),
            ("-p", "other", "ps"),
            ("-pother", "ps"),
            ("--project-name=other", "ps"),
            ("--project-directory=/tmp", "ps"),
            ("--ansi", "never", "ps"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(envelope.ExecutionEnvelopeRefused):
                    envelope.validate_compose_arguments("base", arguments)

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
                with self.assertRaises(envelope.ExecutionEnvelopeRefused):
                    envelope.validate_compose_arguments(
                        "automation", ("run", option, value, "sentinel-automation"))

    def test_application_arguments_begin_after_service(self):
        envelope.validate_compose_arguments(
            "automation",
            ("run", "--rm", "-T", "--no-deps", "sentinel-automation",
             "--", "--profile", "application-value", "-e", "application-value"))

    def test_destructive_volume_and_orphan_flags_are_refused(self):
        cases = (
            ("down", "-v"), ("down", "--volumes"),
            ("down", "--remove-orphans"), ("down", "--rmi=all"),
            ("rm", "--volumes", "sentinel"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(envelope.ExecutionEnvelopeRefused):
                    envelope.validate_compose_arguments("automation", arguments)

    def test_startup_identity_changing_flags_are_refused(self):
        cases = (
            ("up", "--build"), ("up", "--pull", "always"),
            ("up", "--remove-orphans"), ("up", "--renew-anon-volumes"),
            ("up", "--scale", "sentinel-automation=2"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(envelope.ExecutionEnvelopeRefused):
                    envelope.validate_compose_arguments("automation", arguments)

    def test_supported_fixed_operations_pass(self):
        cases = (
            ("automation", ("--profile", "automation", "ps")),
            ("automation", ("--ansi", "never", "--progress=plain", "logs")),
            ("automation", ("up", "-d", "--no-deps", "--force-recreate", "sentinel-automation")),
            ("automation", ("down", "--timeout", "30")),
            ("base", ("run", "--rm", "-T", "sentinel", "status")),
            ("base", ("up", "-d", "--no-deps", "--force-recreate", "sentinel-panel")),
            ("base", ("ps", "-q", "sentinel-panel")),
        )
        for surface, arguments in cases:
            with self.subTest(surface=surface, arguments=arguments):
                envelope.validate_compose_arguments(surface, arguments)

    def test_wrappers_bind_guard_project_and_context(self):
        base = (SCRIPTS / "sentinel-compose.sh").read_text(encoding="utf-8")
        automation = (SCRIPTS / "sentinel-automation-compose.sh").read_text(encoding="utf-8")
        env_bridge = (SCRIPTS / "sentinel-env.sh").read_text(encoding="utf-8")
        emergency = (SCRIPTS / "sentinel-emergency-kill.sh").read_text(encoding="utf-8")
        volume = (SCRIPTS / "sentinel-state-volume-permissions.sh").read_text(encoding="utf-8")

        base_guard = 'scripts/sentinel_execution_envelope.py \\\n    compose --surface base -- "$@"'
        automation_guard = 'scripts/sentinel_execution_envelope.py \\\n  compose --surface automation -- "$@"'
        self.assertIn(base_guard, base)
        self.assertIn(automation_guard, automation)
        self.assertIn("--project-name sentinel", base)
        self.assertIn("--project-name sentinel", automation)
        self.assertIn("docker --context default compose", base)
        self.assertIn("docker --context default compose", automation)
        self.assertIn("sentinel_execution_envelope.py environment", env_bridge)
        self.assertIn("export DOCKER_CONTEXT=default", env_bridge)
        self.assertIn("docker --context default compose", emergency)
        self.assertIn("--project-name sentinel", emergency)
        self.assertIn("docker --context default volume inspect", volume)
        self.assertIn("docker --context default run", volume)


if __name__ == "__main__":
    unittest.main()
