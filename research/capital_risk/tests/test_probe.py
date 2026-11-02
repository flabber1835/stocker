import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("risk_probe", Path(__file__).parents[1] / "probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeGuards(unittest.TestCase):
    def setUp(self):
        self.env = dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY=probe.REPOSITORY,
                        GITHUB_REF=probe.BRANCH, GITHUB_ACTOR=probe.ACTOR,
                        RUNNER_ENVIRONMENT="github-hosted", RUNNER_OS="Linux",
                        GITHUB_EVENT_NAME="push", GITHUB_SHA="a" * 40)
        self.request = dict(schema="research.capital-risk-request/1", request_id="probe-001",
                            stage="probe", protocol_sha256="b" * 64)

    def test_exact_context_is_admitted(self):
        probe.check_context(self.env)

    def test_other_contexts_are_refused(self):
        for key, value in [("GITHUB_REPOSITORY", "other/repo"), ("GITHUB_REF", "refs/heads/main"),
                           ("GITHUB_ACTOR", "someone"), ("RUNNER_ENVIRONMENT", "self-hosted"),
                           ("RUNNER_OS", "Windows"), ("GITHUB_ACTIONS", "false"),
                           ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_SHA", "unknown")]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                probe.check_context({**self.env, key: value})

    def test_production_credentials_are_refused(self):
        for name in probe.FORBIDDEN_CREDENTIALS:
            with self.subTest(name=name), self.assertRaises(ValueError):
                probe.check_context({**self.env, name: "synthetic-falsifier"})

    def test_probe_cannot_be_used_to_launch_replay(self):
        probe.validate_request(self.request)
        for changed in [{"stage": "baseline"}, {"extra": "secret"}, {"protocol_sha256": "bad"}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                probe.validate_request({**self.request, **changed})

    def test_report_is_confined_to_artifact_directory(self):
        workspace = Path.cwd() / "synthetic-unused-workspace"
        good = workspace / "artifacts/capital-risk/probe.json"
        self.assertEqual(probe.admitted_output(workspace, good), good.resolve())
        for bad in [workspace / "source.json", workspace / "../outside.json",
                    workspace / "artifacts/capital-risk/inputs.zip"]:
            with self.subTest(path=bad), self.assertRaises(ValueError):
                probe.admitted_output(workspace, bad)


if __name__ == "__main__":
    unittest.main()
