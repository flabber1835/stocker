"""Emergency fencing must survive broken runtime and Compose authority."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT = ROOT / "scripts" / "sentinel-emergency-kill.sh"


class EmergencyKillBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copyfile(SCRIPT, scripts / SCRIPT.name)
        (scripts / "sentinel_host_python.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8")
        binary = self.root / "bin"
        binary.mkdir()
        docker = binary / "docker"
        docker.write_text(
            "#!" + sys.executable + "\n"
            "import os, sys\n"
            "from pathlib import Path\n"
            "args=sys.argv[1:]\n"
            "Path('docker-calls').open('a',encoding='utf-8').write(' '.join(args)+'\\n')\n"
            "if 'ps' in args:\n"
            "    ids=os.environ.get('FAKE_POSTGRES_IDS','abc123').split(',')\n"
            "    for value in ids:\n"
            "        if value: print(value)\n"
            "    raise SystemExit(0)\n"
            "if 'exec' in args:\n"
            "    Path('docker-exec-ran').write_text('yes',encoding='utf-8')\n"
            "    Path('emergency.sql').write_text(sys.stdin.read(),encoding='utf-8')\n"
            "    print('automation_kill_engaged:true generation=8')\n"
            "    raise SystemExit(int(os.environ.get('FAKE_EXEC_RC','0')))\n"
            "raise SystemExit(91)\n",
            encoding="utf-8")
        docker.chmod(0o700)
        self.process = {
            "PATH": str(binary) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "SENTINEL_HOST_PYTHON": sys.executable,
            "FAKE_POSTGRES_IDS": "abc123",
        }

    def run_script(self, *arguments, extra_env=None):
        env = dict(self.process)
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", "scripts/sentinel-emergency-kill.sh", *arguments],
            cwd=str(self.root), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=10)

    def test_targets_exact_canonical_postgres_and_direct_sql(self):
        result = self.run_script(
            "--actor", "deploy-agent", "--reason", "fail closed")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.root / "docker-calls").read_text(encoding="utf-8")
        self.assertIn("--context default ps -q", calls)
        self.assertIn("label=com.docker.compose.project=sentinel", calls)
        self.assertIn("label=com.docker.compose.service=sentinel-postgres", calls)
        self.assertIn("--context default exec -i abc123 psql", calls)
        sql = (self.root / "emergency.sql").read_text(encoding="utf-8")
        self.assertIn("UPDATE sentinel_automation_control", sql)
        self.assertIn("kill_switch_engaged=TRUE", sql)
        self.assertIn("UPDATE sentinel_automation_lease", sql)
        self.assertIn("KILL_ENGAGED", sql)
        self.assertIn("WHERE id=1 AND NOT kill_switch_engaged", sql)
        self.assertIn("ON_ERROR_STOP=1", calls)
        self.assertIn("actor=deploy-agent", calls)
        self.assertIn("reason=fail closed", calls)

    def test_broken_compose_and_runtime_environment_cannot_redirect_fence(self):
        result = self.run_script(extra_env={
            "COMPOSE_FILE": "/tmp/evil.yml",
            "COMPOSE_PROJECT_NAME": "other",
            "COMPOSE_PROFILES": "shadow",
            "SENTINEL_RUNTIME_IMAGE_REF": "evil/runtime:latest",
            "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "f" * 64,
            "DOCKER_HOST": "tcp://example.invalid:2375",
            "DOCKER_CONTEXT": "remote",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.root / "docker-calls").read_text(encoding="utf-8")
        self.assertNotIn("compose", calls)
        self.assertNotIn("evil", calls)
        self.assertNotIn("remote", calls)
        self.assertIn("--context default", calls)

    def test_zero_or_multiple_postgres_containers_refuse_before_exec(self):
        for ids in ("", "abc123,def456"):
            with self.subTest(ids=ids):
                for marker in ("docker-calls", "docker-exec-ran", "emergency.sql"):
                    (self.root / marker).unlink(missing_ok=True)
                result = self.run_script(extra_env={"FAKE_POSTGRES_IDS": ids})
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn("not unique", result.stderr)
                self.assertFalse((self.root / "docker-exec-ran").exists())

    def test_argument_validation_refuses_before_docker(self):
        cases = (
            ("--actor", ""),
            ("--reason", "   "),
            ("--actor", "a", "--actor", "b"),
            ("--unknown", "x"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                (self.root / "docker-calls").unlink(missing_ok=True)
                result = self.run_script(*arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("REFUSED", result.stderr)
                self.assertFalse((self.root / "docker-calls").exists())

    def test_script_has_no_compose_or_sentinel_runtime_dependency(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("docker compose", source)
        self.assertNotIn("docker --context default compose", source)
        self.assertNotIn("SENTINEL_RUNTIME_IMAGE_REF", source)
        self.assertNotIn("docker-compose.sentinel", source)
        self.assertIn("sentinel_automation_control", source)
        self.assertIn("sentinel_automation_lease", source)


if __name__ == "__main__":
    unittest.main()
