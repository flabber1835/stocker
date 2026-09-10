"""Offline adversarial env harness, including real host launcher boundaries.

Run: python -m unittest -v tests.host_python38.test_env_ingestion
Each generated case is a separately reported regression, also collected by pytest.
"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_env as env


def _module(name):
    spec = importlib.util.spec_from_file_location("env_harness_" + name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GO = _module("sentinel_go_validate")
DEPLOY = _module("sentinel_autonomous_deploy")
RUNTIME = _module("sentinel_runtime_selection")
BOOTSTRAP = _module("sentinel_deployment_bootstrap")
CONVERT = _module("sentinel-env-from-stocker")
DEPLOY_BOOTSTRAP = _module("sentinel_autonomous_deploy_bootstrap")
LOADERS = {
    "canonical": env.load, "go": GO.load_dotenv_literal,
    "install": DEPLOY.load_dotenv, "runtime": RUNTIME._load_dotenv_literal,
    "bootstrap": BOOTSTRAP._parse_env, "conversion": CONVERT.parse_env,
}
ERRORS = (env.EnvRefused, GO.ValidationRefused, DEPLOY.DeployRefused,
          RUNTIME.RuntimeSelectionRefused, BOOTSTRAP.BootstrapRefused, ValueError)
CANARY = "PRIVATE_CANARY_91c64"
BASE = {
    "SENTINEL_POSTGRES_PASSWORD": "synthetic-database-password",
    "SHARADAR_API_KEY": CANARY + "_sharadar",
    "SENTINEL_BACKUP_DIR": "/synthetic/external/backup",
    "ALPACA_API_KEY": CANARY + "_alpaca",
    "ALPACA_SECRET_KEY": CANARY + "_secret",
    "ALPACA_BASE_URL": env.PAPER_URL,
    "SENTINEL_FORCE_CPU_LIMITS": "1",
}
MAINTENANCE_LAUNCHERS = (
    "sentinel-base-backup.sh", "sentinel-backup-status.sh", "sentinel-restore-drill.sh",
    "sentinel-automation-compose.sh", "sentinel-authorized-cli.sh",
)
VALID = {
    "lf": (b"A=one\nB=two\n", {"A": "one", "B": "two"}),
    "crlf": (b"A=one\r\nB=two\r\n", {"A": "one", "B": "two"}),
    "mixed_endings": (b"A=one\r\nB=two\n", {"A": "one", "B": "two"}),
    "no_final_newline": (b"A=one", {"A": "one"}),
    "bom": (b"\xef\xbb\xbfA=one\r\n", {"A": "one"}),
    "empty": (b"", {}),
    "comments": (b"# comment\n \t# next\n\n", {}),
    "empty_values": (b"A=\nB=''\nC=\"\"", {"A": "", "B": "", "C": ""}),
    "spacing": (b" \texport\t A \t= one  \t\n", {"A": "one"}),
    "embedded_hash": (b"A=one#two\n", {"A": "one#two"}),
    "inline_comment": (b"A=one \t# comment\n", {"A": "one"}),
    "empty_inline_comment": (b"A= # enter value\n", {"A": ""}),
    "empty_tab_comment_crlf": (b"A=\t# enter value\r\n", {"A": ""}),
    "empty_comment_no_newline": (b"A=  # enter value", {"A": ""}),
    "leading_literal_hash": (b"A=#literal\nB=' # literal'\n", {"A": "#literal", "B": " # literal"}),
    "single_quote_hash": (b"A='one # two' # comment\n", {"A": "one # two"}),
    "double_quote_hash": (b'A="one # two" # comment\n', {"A": "one # two"}),
    "equals": (b"A=one=two==\n", {"A": "one=two=="}),
    "unicode_value": ("A='Helsinki / café / 東京'\n".encode(), {"A": "Helsinki / café / 東京"}),
    "literal_dollars": (b"A=${UNSET}\nB=$HOME\nC=$$\n", {"A": "${UNSET}", "B": "$HOME", "C": "$$"}),
    "shell_words": (b"A=$(touch CANARY)\nB=`id`; false\n", {"A": "$(touch CANARY)", "B": "`id`; false"}),
    "single_escaped_quote": (b"A='can\\'t'\n", {"A": "can't"}),
    "double_escapes": (b'A="a\\\\b\\\"c"\n', {"A": 'a\\b"c'}),
    "literal_single_backslashes": (b"A='C:\\new\\temp'\n", {"A": "C:\\new\\temp"}),
    "case_sensitive": (b"A=one\na=two\n", {"A": "one", "a": "two"}),
    "unknown_key": (b"FUTURE_SETTING=value\n", {"FUTURE_SETTING": "value"}),
}
INVALID = {
    "no_equals": b"A\n", "shell_source": b"source /tmp/evil\n",
    "no_key": b"=value\n", "numeric_key": b"1A=value\n",
    "hyphen_key": b"A-B=value\n", "dot_key": b"A.B=value\n",
    "space_key": b"A B=value\n", "unicode_key": "АLPACA_KEY=value\n".encode(),
    "unclosed_single": b"A='secret\n", "unclosed_double": b'A="secret\n',
    "multiline": b"A='secret\nnext'\n", "quote_garbage": b'A="secret"trailing\n',
    "adjacent_quote": b'A="secret""other"\n', "quote_no_comment_gap": b"A='secret'#tail\n",
    "duplicate_equal": b"A=one\nA=one\n", "duplicate_conflict": b"A=one\nA=two\n",
    "duplicate_export": b"A=one\n export A = two\n",
    "duplicate_empty": b"A=one\nA=\n", "duplicate_crlf": b"A=one\r\nA=two\r\n",
    "invalid_utf8": b"A=\xff\n", "truncated_utf8": b"A=\xe2\x82",
    "utf16": "A=value\n".encode("utf-16"), "gzip": b"\x1f\x8b\x08\x00",
    "nul": b"A=one\x00two\n", "bare_cr": b"A=one\rB=two\n",
    "final_cr": b"A=one\r", "ansi_escape": b"A=\x1b[31mvalue\n",
    "del": b"A=\x7f\n", "vertical_tab": b"A=one\vB=two\n",
    "form_feed": b"A=one\fB=two\n", "escaped_newline": b'A="one\\ntwo"\n',
    "escaped_tab": b'A="one\\ttwo"\n', "embedded_bom": "A=one\ufefftwo\n".encode(),
    "literal_tab_value": b"A=one\ttwo\n",
    "quoted_tab_value": b"A='one\ttwo'\n",
    "double_bom": b"\xef\xbb\xbf\xef\xbb\xbfA=one\n",
    "bidi": "A=one\u202etwo\n".encode(), "zero_width": "A=one\u200btwo\n".encode(),
    "unicode_line_separator": "A=one\u2028B=two\n".encode(),
    "unicode_paragraph_separator": "A=one\u2029B=two\n".encode(),
    "noncharacter": "A=one\ufffftwo\n".encode(),
    "control_in_comment": b"# hidden\x00\nA=value\n",
    "shell_env": b"BASH_ENV=/tmp/evil\n", "python_path": b"PYTHONPATH=/tmp/evil\n",
}


class EnvHarness(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / ".env"

    def write(self, values=None, *, raw=None):
        body = raw if raw is not None else "".join(
            "%s=%s\n" % item for item in (BASE if values is None else values).items()).encode()
        self.path.write_bytes(body)
        return body

    def test_optional_missing_file_and_required_file(self):
        self.assertEqual(env.load(self.path), {})
        with self.assertRaisesRegex(env.EnvRefused, "MISSING_FILE"):
            env.load(self.path, required=True)

    def test_deterministic_control_byte_campaign(self):
        for byte in list(range(32)) + list(range(127, 160)):
            if byte in (9, 10, 13):
                continue
            for position in (0, 1, 8):
                with self.subTest(byte=byte, position=position):
                    text = "A=CANARY"[:position] + chr(byte) + "A=CANARY"[position:]
                    with self.assertRaises(env.EnvRefused):
                        env.parse_bytes(text.encode())

    def test_seeded_mutation_and_order_independence(self):
        rng = random.Random(9102026)
        rows = ["KEY_%d=value_%d" % (i, i) for i in range(25)]
        expected = dict(row.split("=", 1) for row in rows)
        for iteration in range(100):
            rng.shuffle(rows)
            raw = ("\r\n" if iteration % 2 else "\n").join(rows).encode()
            self.assertEqual(env.parse_bytes(raw), expected)
            split = rng.randrange(len(raw))
            with self.assertRaises(env.EnvRefused):
                env.parse_bytes(raw[:split] + b"\0" + raw[split:])
            duplicate = raw + b"\n" + rng.choice(rows).encode()
            with self.assertRaisesRegex(env.EnvRefused, "DUPLICATE_KEY"):
                env.parse_bytes(duplicate)

    def test_valid_invalid_valid_retry_does_not_cache_state(self):
        self.write()
        expected = env.load(self.path)
        self.write(raw=b"A=one\nA=two\n")
        with self.assertRaises(env.EnvRefused):
            env.load(self.path)
        self.write()
        self.assertEqual(env.load(self.path), expected)

    def test_failed_load_does_not_partially_update_process(self):
        self.write(raw=b"SHARADAR_API_KEY=new\nBROKEN\n")
        with mock.patch.dict(os.environ, {"SHARADAR_API_KEY": "old"}, clear=True):
            for loader in (GO.merged_environment, DEPLOY.merged_environment):
                with self.assertRaises(ERRORS):
                    loader(self.path)
                self.assertEqual(dict(os.environ), {"SHARADAR_API_KEY": "old"})

    def test_explicit_empty_process_value_is_authoritative_and_refused(self):
        self.write()
        with mock.patch.dict(os.environ, {"SHARADAR_API_KEY": ""}, clear=True):
            for loader in (GO.merged_environment, DEPLOY.merged_environment):
                resolved = loader(self.path)
                self.assertEqual(resolved["SHARADAR_API_KEY"], "")
                with self.assertRaisesRegex(env.EnvRefused, "SHARADAR_API_KEY"):
                    env.validate(resolved, profile="install")

    def test_process_override_cannot_hide_malformed_file(self):
        self.write(raw=b"SHARADAR_API_KEY=bad\nSHARADAR_API_KEY=again\n")
        with mock.patch.dict(os.environ, BASE, clear=True):
            with self.assertRaises(GO.ValidationRefused):
                GO.merged_environment(self.path)

    def test_file_size_and_line_size_bounds(self):
        with self.assertRaisesRegex(env.EnvRefused, "FILE_TOO_LARGE"):
            env.parse_bytes(b"#" * (env.MAX_BYTES + 1))
        self.write(raw=b"A=" + b"x" * env.MAX_LINE_BYTES)
        with self.assertRaisesRegex(env.EnvRefused, "LINE_TOO_LONG"):
            env.load(self.path)
        self.write(raw=b"A=" + b"x" * (env.MAX_LINE_BYTES - 2))
        self.assertEqual(len(env.load(self.path)["A"]), env.MAX_LINE_BYTES - 2)
        self.write(raw=b"#" * (env.MAX_BYTES + 1))
        with self.assertRaisesRegex(env.EnvRefused, "FILE_TOO_LARGE"):
            env.load(self.path)

    def test_permission_denied_and_io_error_are_redacted(self):
        self.write()
        for code in (errno.EACCES, errno.EIO, errno.ESTALE):
            with mock.patch.object(env.os, "open", side_effect=OSError(code, CANARY)):
                with self.assertRaisesRegex(env.EnvRefused, "UNREADABLE") as raised:
                    env.load(self.path)
                self.assertNotIn(CANARY, str(raised.exception))

    def test_read_failure_closes_descriptor(self):
        self.write()
        real_close = env.os.close
        with mock.patch.object(env.os, "read", side_effect=OSError(errno.EIO, CANARY)):
            with mock.patch.object(env.os, "close", wraps=real_close) as closed:
                with self.assertRaises(env.EnvRefused):
                    env.load(self.path)
                self.assertEqual(closed.call_count, 1)

    def test_short_read_chunks_are_joined(self):
        self.write()
        real_read = env.os.read
        with mock.patch.object(env.os, "read", side_effect=lambda fd, size: real_read(fd, min(size, 3))):
            self.assertEqual(env.load(self.path), BASE)

    def test_atomic_replacement_during_read_is_refused(self):
        self.write()
        replacement = self.root / "replacement"
        replacement.write_bytes(self.path.read_bytes())
        real_read = env.os.read
        changed = []
        def read(fd, size):
            data = real_read(fd, size)
            if not changed:
                changed.append(True)
                os.replace(str(replacement), str(self.path))
            return data
        with mock.patch.object(env.os, "read", side_effect=read):
            with self.assertRaisesRegex(env.EnvRefused, "FILE_CHANGED"):
                env.load(self.path)

    def test_in_place_truncation_and_same_size_mutation_are_refused(self):
        original = self.write()
        real_read = env.os.read
        for updated in (b"", original.replace(b"synthetic", b"different")):
            self.write()
            changed = []
            def read(fd, size):
                data = real_read(fd, size)
                if not changed:
                    changed.append(True)
                    self.path.write_bytes(updated)
                return data
            with mock.patch.object(env.os, "read", side_effect=read):
                with self.assertRaisesRegex(env.EnvRefused, "FILE_CHANGED"):
                    env.load(self.path)

    def test_swap_to_symlink_between_stat_and_open_is_refused(self):
        self.write()
        target = self.root / "target"
        target.write_text("A=secret\n")
        real_open = env.os.open
        def swapped(*args, **kwargs):
            self.path.unlink()
            self.path.symlink_to(target)
            return real_open(*args, **kwargs)
        with mock.patch.object(env.os, "open", side_effect=swapped):
            with self.assertRaises(env.EnvRefused):
                env.load(self.path)

    def test_bootstrap_missing_inputs_block_even_with_existing_key(self):
        for key in ("SHARADAR_API_KEY", "SENTINEL_POSTGRES_PASSWORD", "SENTINEL_BACKUP_DIR"):
            values = dict(BASE, **{env.RECEIPT_KEY: "a" * 64})
            del values[key]
            before = self.write(values)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch.object(BOOTSTRAP, "_run", side_effect=AssertionError("external command")):
                    with self.assertRaisesRegex(BOOTSTRAP.BootstrapRefused, key):
                        BOOTSTRAP.ensure_publication_receipt_key(self.path)
            self.assertEqual(self.path.read_bytes(), before)

    def test_blank_receipt_remains_owned_by_existing_bootstrap(self):
        self.write(dict(BASE, **{env.RECEIPT_KEY: ""}))
        with mock.patch.dict(os.environ, {}, clear=True):
            result = BOOTSTRAP.ensure_publication_receipt_key(
                self.path, receipt_state_probe=lambda _: BOOTSTRAP.SAFE_FRESH_DATABASE)
        self.assertTrue(result.startswith("GENERATED_"))
        self.assertEqual(len(env.load(self.path)[env.RECEIPT_KEY]), 64)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_receipt_write_roundtrips_bom_crlf_and_tab_export(self):
        for prefix in ("\ufeff", "export\t", "\ufeffexport\t"):
            with self.subTest(prefix=ascii(prefix)):
                self.write(raw=((prefix + env.RECEIPT_KEY + "=\r\n") +
                                "".join("%s=%s\r\n" % item for item in BASE.items())).encode())
                with mock.patch.dict(os.environ, {}, clear=True):
                    result = BOOTSTRAP.ensure_publication_receipt_key(
                        self.path, receipt_state_probe=lambda _: BOOTSTRAP.SAFE_FRESH_DATABASE)
                self.assertTrue(result.startswith("GENERATED_"))
                self.assertEqual(len(env.load(self.path)[env.RECEIPT_KEY]), 64)

    def test_managed_fact_write_roundtrips_bom_and_tab_export(self):
        for writer in (DEPLOY.update_dotenv, DEPLOY_BOOTSTRAP._safe_update_dotenv):
            for prefix in ("\ufeff", "export\t", "\ufeffexport\t"):
                with self.subTest(writer=writer.__name__, prefix=ascii(prefix)):
                    self.write(raw=(prefix + "SENTINEL_GIT_COMMIT=old\r\n").encode())
                    writer(self.path, {"SENTINEL_GIT_COMMIT": "a" * 40})
                    self.assertEqual(env.load(self.path), {"SENTINEL_GIT_COMMIT": "a" * 40})

    def test_shadow_target_has_no_broker_prerequisite(self):
        values = {k: v for k, v in BASE.items() if not k.startswith("ALPACA_")}
        env.validate(values, profile="go", target="SHADOW")
        with self.assertRaisesRegex(env.EnvRefused, "ALPACA_API_KEY"):
            env.validate(values, profile="go", target="DUAL_RUN_OBSERVATION")

    def test_private_record_protocol_failure_emits_no_partial_values(self):
        self.write(raw=("A=%s\nBAD\n" % CANARY).encode())
        result = subprocess.run([sys.executable, str(ROOT / "scripts/sentinel_env.py"),
                                 "--env-file", str(self.path), "--profile", "install", "--records"],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(CANARY.encode(), result.stderr)

    def shell_repo(self):
        scripts = self.root / "scripts"
        scripts.mkdir(exist_ok=True)
        for name in ("sentinel_env.py", "sentinel-env.sh", "sentinel-compose.sh", "sentinel-autonomous-deploy.sh", "sentinel-go-validate.sh", "sentinel-bringup.sh"):
            shutil.copyfile(ROOT / "scripts" / name, scripts / name)
        (scripts / "sentinel_host_python.py").write_text("pass\n")
        # Every downstream operation records a canary; invalid env must never
        # reach these substitutes. No database, Docker daemon or network exists.
        for name in ("sentinel_deployment_bootstrap.py", "sentinel_go_host_preflight.py", "sentinel_runtime_selection.py", "sentinel_go_account_preflight.py", "sentinel_go_verified_entry.py"):
            (scripts / name).write_text(
                "from pathlib import Path\nPath('effects').open('a').write('" + name + "\\n')\nraise SystemExit(93)\n")
        (scripts / "sentinel-backup-lib.sh").write_text("sentinel_backup_root() { echo backup >> effects; }\n")
        (scripts / "sentinel_feed_gate.py").write_text("raise SystemExit(1)\n")
        binary = self.root / "bin"
        binary.mkdir(exist_ok=True)
        for name in ("git", "docker"):
            (binary / name).write_text(
                "#!" + sys.executable + "\nimport json, os, sys\nfrom pathlib import Path\n"
                "Path('effects').open('a').write('" + name + "\\n')\n"
                "Path('selected.json').write_text(json.dumps({k:v for k,v in os.environ.items() if k.startswith(('SENTINEL_', 'SHARADAR_', 'ALPACA_', 'COMPOSE_'))}))\n"
                + ("if sys.argv[1] == 'symbolic-ref': print('main')\n"
                   "elif sys.argv[1] == 'rev-parse': print('a'*40)\n" if name == "git" else ""))
            (binary / name).chmod(0o700)
        return {"PATH": str(binary) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
                "SENTINEL_HOST_PYTHON": sys.executable, "SENTINEL_GO_LOCK_HELD": "1"}

    def run_shell(self, launcher, process, *args):
        return subprocess.run(["bash", "scripts/" + launcher] + list(args), cwd=str(self.root),
                              env=process, capture_output=True, text=True, timeout=10)

    def test_compose_consumes_file_values_literally_and_process_wins(self):
        process = self.shell_repo()
        values = dict(BASE, SHARADAR_API_KEY="$(touch PWNED); `touch PWNED2` #hash $HOME")
        self.write(values)
        # Quote the intentional whitespace-prefixed hash.
        self.path.write_text(self.path.read_text().replace(
            "SHARADAR_API_KEY=" + values["SHARADAR_API_KEY"],
            "SHARADAR_API_KEY='" + values["SHARADAR_API_KEY"] + "'"))
        process["ALPACA_API_KEY"] = "process-wins"
        result = self.run_shell("sentinel-compose.sh", process, "--run", "up", "-d")
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = json.loads((self.root / "selected.json").read_text())
        self.assertEqual(selected["SHARADAR_API_KEY"], values["SHARADAR_API_KEY"])
        self.assertEqual(selected["ALPACA_API_KEY"], "process-wins")
        self.assertEqual(selected["SENTINEL_BACKUP_DIR"], BASE["SENTINEL_BACKUP_DIR"])
        self.assertEqual(selected["COMPOSE_DISABLE_ENV_FILE"], "1")
        self.assertEqual(selected["COMPOSE_ENV_FILES"], "/dev/null")
        self.assertFalse((self.root / "PWNED").exists())
        self.assertFalse((self.root / "PWNED2").exists())
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_incomplete_loader_pipe_cannot_export_or_start_compose(self):
        process = self.shell_repo()
        process.update(BASE)
        self.write()
        (self.root / "scripts/sentinel_env.py").write_text(
            "import sys\nsys.stdout.buffer.write(b'SHARADAR_API_KEY=partial\\0')\nraise SystemExit(7)\n")
        result = self.run_shell("sentinel-compose.sh", process, "--run", "up")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / "effects").exists())

    def test_fresh_blank_receipt_is_not_exported_as_an_empty_override(self):
        process = self.shell_repo()
        self.write(dict(BASE, **{env.RECEIPT_KEY: ""}))
        (self.root / "scripts/sentinel_deployment_bootstrap.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "assert 'SENTINEL_PUBLICATION_RECEIPT_KEY' not in os.environ\n"
            "Path('effects').write_text('bootstrap-reached')\nraise SystemExit(93)\n")
        result = self.run_shell("sentinel-go-validate.sh", process)
        self.assertEqual(result.returncode, 93, result.stderr)
        self.assertEqual((self.root / "effects").read_text(), "bootstrap-reached")

    def test_validated_runtime_pointer_keeps_precedence_over_file_and_shell(self):
        process = self.shell_repo()
        process["SENTINEL_RUNTIME_IMAGE_REF"] = "sentinel:stale-shell"
        self.write(dict(BASE, SENTINEL_RUNTIME_IMAGE_REF="sentinel:stale-file"))
        pointer = self.root / "artifacts/sentinel/deployment/validated-runtime.env"
        pointer.parent.mkdir(parents=True)
        expected = "sha256:" + "a" * 64
        pointer.write_text("SENTINEL_RUNTIME_IMAGE_REF=" + expected + "\n")
        result = self.run_shell("sentinel-compose.sh", process, "--run", "up")
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = json.loads((self.root / "selected.json").read_text())
        self.assertEqual(selected["SENTINEL_RUNTIME_IMAGE_REF"], expected)

    def test_quote_roundtrip_property_for_generated_secrets(self):
        rng = random.Random(304305)
        alphabet = "abcXYZ019 /'\"#$`\\;:=(){}[]-_é"
        for length in range(1, 150):
            value = "".join(rng.choice(alphabet) for _ in range(length))
            raw = ("A=" + CONVERT.quote(value)).encode()
            self.assertEqual(env.parse_bytes(raw), {"A": value})

    def test_cli_success_reports_no_values(self):
        self.write()
        result = subprocess.run([sys.executable, str(ROOT / "scripts/sentinel_env.py"),
                                 "--env-file", str(self.path), "--profile", "install"],
                                env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "environment preflight: PASS (install)\n")
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_alternate_compose_env_file_is_not_silently_accepted(self):
        with self.assertRaisesRegex(env.EnvRefused, "ALTERNATE_COMPOSE"):
            env.merge(BASE, {"COMPOSE_ENV_FILES": "another.env"})

    def test_shell_refuses_explicit_empty_receipt_before_bootstrap(self):
        process = self.shell_repo()
        process[env.RECEIPT_KEY] = ""
        self.write()
        result = self.run_shell("sentinel-go-validate.sh", process)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.root / "effects").exists())

    def test_exception_never_includes_a_malformed_key_or_line(self):
        for raw in ((CANARY + "-BAD=value\n").encode(), (CANARY + " invalid\n").encode()):
            with self.assertRaises(env.EnvRefused) as raised:
                env.parse_bytes(raw)
            self.assertNotIn(CANARY, str(raised.exception))

    def test_go_cli_shadow_target_overrides_file_target(self):
        process = self.shell_repo()
        values = {k: v for k, v in BASE.items() if not k.startswith("ALPACA_")}
        values["SENTINEL_GO_TARGET"] = "DUAL_RUN_OBSERVATION"
        self.write(values)
        result = self.run_shell("sentinel-go-validate.sh", process, "--target=SHADOW")
        self.assertEqual(result.returncode, 93, result.stderr)
        self.assertIn("sentinel_deployment_bootstrap.py", (self.root / "effects").read_text())

    def test_command_merge_refuses_file_control_keys_even_with_process_override(self):
        for key in ("RUN", "PRODUCTION_RUN", "FORWARDED_ARGS", "RUNTIME_POINTER",
                    "CANONICAL", "BACKUP", "GENERATED", "INITIALIZE_BACKUP",
                    "record", "records", "BASH_XTRACEFD", "GIT_CONFIG_COUNT",
                    "DOCKER_HOST", "COMPOSE_FILE", "SENTINEL_HOST_PYTHON",
                    "SENTINEL_GO_LOCK_HELD", "SENTINEL_BASE_BACKUP_LOCK_FD"):
            with self.subTest(key=key):
                with self.assertRaises(env.EnvRefused):
                    env.merge(dict(BASE, **{key: CANARY}), {key: "safe-process"})

    def test_go_arguments_cannot_weaken_preflight_or_select_another_file(self):
        process = self.shell_repo()
        other = self.root / "other.env"
        other.write_bytes(self.write())
        self.write({k: v for k, v in BASE.items() if k != "ALPACA_API_KEY"})
        for args in (("--profile", "compose"), ("--env-file", str(other))):
            with self.subTest(option=args[0]):
                result = self.run_shell("sentinel-go-validate.sh", process, *args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("ALPACA_API_KEY", result.stderr)
                self.assertFalse((self.root / "effects").exists())

    def test_command_merge_preserves_application_extensions_and_external_controls(self):
        values = dict(BASE, SENTINEL_FUTURE_SETTING="literal", GITHUB_TOKEN=CANARY)
        resolved = env.merge(values, {"PATH": "/usr/bin", "SENTINEL_HOST_PYTHON": sys.executable})
        self.assertEqual(resolved["SENTINEL_FUTURE_SETTING"], "literal")
        self.assertEqual(resolved["GITHUB_TOKEN"], CANARY)
        self.assertEqual(resolved["PATH"], "/usr/bin")
        self.assertEqual(resolved["SENTINEL_HOST_PYTHON"], sys.executable)

    def test_python_command_loaders_refuse_shell_control_assignments(self):
        self.write(dict(BASE, RUN="0"))
        with mock.patch.dict(os.environ, {}, clear=True):
            for loader in (GO.merged_environment, DEPLOY.merged_environment):
                with self.assertRaises(ERRORS):
                    loader(self.path)
            with mock.patch.object(RUNTIME, "_load_dotenv_literal", lambda: env.load(self.path)):
                with self.assertRaises(RUNTIME.RuntimeSelectionRefused):
                    RUNTIME._merged_environment()

    def test_empty_commented_credentials_block_install_before_git(self):
        process = self.shell_repo()
        for key in ("SHARADAR_API_KEY", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
            for suffix in (" # enter value\n", "\t# enter value\r\n", "  # enter value"):
                with self.subTest(key=key, ending=repr(suffix[-2:])):
                    raw = self.write({k: v for k, v in BASE.items() if k != key})
                    self.write(raw=raw + (key + "=" + suffix).encode())
                    result = self.run_shell("sentinel-autonomous-deploy.sh", process)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(key, result.stderr)
                    self.assertFalse((self.root / "effects").exists())

    def maintenance_repo(self):
        process = self.shell_repo()
        for name in MAINTENANCE_LAUNCHERS:
            shutil.copyfile(ROOT / "scripts" / name, self.root / "scripts" / name)
        (self.root / "scripts/sentinel-backup-lib.sh").write_text(
            'sentinel_backup_root() { echo backup >> effects; printf "%s\\n" "$SENTINEL_BACKUP_DIR"; }\n')
        (self.root / "scripts/sentinel_backup_lock.py").write_text("pass\n")
        docker = self.root / "bin/docker"
        docker.write_text(docker.read_text() + "raise SystemExit(93)\n")
        authority = self.root / "authority"
        authority.mkdir(exist_ok=True)
        # Maintenance must work while broker/data credentials are unavailable.
        values = {
            "SENTINEL_BACKUP_DIR": BASE["SENTINEL_BACKUP_DIR"],
            "SENTINEL_POSTGRES_PASSWORD": BASE["SENTINEL_POSTGRES_PASSWORD"],
            env.RECEIPT_KEY: CANARY + "_receipt_0123456789abcdef",
            "SENTINEL_RUNTIME_IMAGE_DIGEST": "sha256:" + "a" * 64,
            "SENTINEL_TEST_IMAGE_DIGEST": "sha256:" + "b" * 64,
            "SENTINEL_GIT_COMMIT": "c" * 40,
            "SENTINEL_AUTHORITY_ARTIFACTS_DIR": str(authority),
        }
        return process, values


def _valid_case(loader, raw, expected):
    def test(self):
        self.write(raw=raw)
        self.assertEqual(loader(self.path), expected)
    return test


def _invalid_case(loader, raw):
    def test(self):
        self.write(raw=("SAFE=%s\n" % CANARY).encode() + raw)
        with self.assertRaises(ERRORS) as raised:
            loader(self.path)
        self.assertNotIn(CANARY, str(raised.exception))
    return test


def _file_type_case(kind):
    def test(self):
        if kind == "directory":
            self.path.mkdir()
        elif kind == "fifo":
            os.mkfifo(str(self.path))
        elif kind == "mode000":
            self.write()
            self.path.chmod(0)
        else:
            target = self.root / "target"
            if kind == "symlink":
                target.write_text("A=value\n")
            self.path.symlink_to(target)
        for name, loader in LOADERS.items():
            with self.subTest(loader=name):
                with self.assertRaises(ERRORS):
                    loader(self.path)
    return test


def _missing_case(key, value):
    def test(self):
        values = dict(BASE)
        if value is None:
            del values[key]
        else:
            values[key] = value
        with self.assertRaisesRegex(env.EnvRefused, key):
            env.validate(values, profile="install")
    return test


def _shell_case(launcher, case):
    def test(self):
        process = self.shell_repo()
        before = self.write()
        if case == "valid":
            pass
        elif case == "missing_file":
            self.path.unlink()
        elif case == "missing_required":
            self.write({k: v for k, v in BASE.items() if k != "SENTINEL_BACKUP_DIR"})
        elif case == "empty_override":
            process["SENTINEL_BACKUP_DIR"] = ""
        else:
            self.write(raw=before + INVALID[case])
        before = self.path.read_bytes() if self.path.exists() else None
        result = self.run_shell(launcher, process, *(('--run', 'up') if launcher == 'sentinel-compose.sh' else ()))
        if case == "valid":
            self.assertIn(result.returncode, (0, 93), result.stderr)
            self.assertTrue((self.root / "effects").exists())
        else:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((self.root / "effects").exists(), result.stderr)
            self.assertIn("REFUSED", result.stderr)
        self.assertNotIn(CANARY, result.stdout + result.stderr)
        self.assertEqual(self.path.read_bytes() if self.path.exists() else None, before)
    return test


def _semantic_case(key, value, accepted):
    def test(self):
        values = dict(BASE, **{key: value})
        if accepted:
            env.validate(values, profile="install")
        else:
            with self.assertRaises(env.EnvRefused):
                env.validate(values, profile="install")
    return test


def _shell_control_case(launcher, key):
    def test(self):
        if launcher in MAINTENANCE_LAUNCHERS:
            process, values = self.maintenance_repo()
        else:
            process, values = self.shell_repo(), dict(BASE)
        values[key] = "0"
        self.write(values)
        result = self.run_shell(launcher, process, *(('--run', 'up') if launcher == 'sentinel-compose.sh' else ()))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.root / "effects").exists())
        self.assertIn("REFUSED", result.stderr)
        self.assertNotIn(CANARY, result.stdout + result.stderr)
    return test


def _maintenance_case(launcher, case):
    def test(self):
        process, values = self.maintenance_repo()
        expected = dict(values)
        if case == "process_only":
            process.update(values)
        else:
            if case.startswith("missing_"):
                del values[case[len("missing_"):]]
            if case == "literal_override":
                values["SENTINEL_POSTGRES_PASSWORD"] = "db$UNSET"
                values[env.RECEIPT_KEY] += " # literal $HOME `text`"
                process["SENTINEL_BACKUP_DIR"] = "/process/backup"
                expected = dict(values, SENTINEL_BACKUP_DIR="/process/backup")
            raw = "".join(k + "=" + CONVERT.quote(v) + "\r\n" for k, v in values.items()).encode()
            if case in INVALID:
                raw += INVALID[case]
            self.write(raw=raw)
            if case == "empty_override":
                process["SENTINEL_POSTGRES_PASSWORD"] = ""
        args = ("status",) if "compose" in launcher or "authorized" in launcher else ()
        result = self.run_shell(launcher, process, *args)
        if case in ("valid", "literal_override", "process_only"):
            self.assertIn(result.returncode, (4, 93), result.stderr)
            self.assertIn("docker", (self.root / "effects").read_text())
            selected = json.loads((self.root / "selected.json").read_text())
            for key, value in expected.items():
                self.assertEqual(selected[key], value, key)
            self.assertEqual(selected["COMPOSE_ENV_FILES"], "/dev/null")
            self.assertEqual(selected["COMPOSE_DISABLE_ENV_FILE"], "1")
        else:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((self.root / "effects").exists(), result.stderr)
        self.assertNotIn(CANARY, result.stdout + result.stderr)
    return test


# Generated unittest methods are individually reported in both the 3.8 CI lane
# and pytest/JUnit. IDs contain scenario names only, never environment values.
for loader_name, loader in LOADERS.items():
    for case, (raw, expected) in VALID.items():
        setattr(EnvHarness, "test_accept_%s_%s" % (loader_name, case), _valid_case(loader, raw, expected))
    for case, raw in INVALID.items():
        setattr(EnvHarness, "test_refuse_%s_%s" % (loader_name, case), _invalid_case(loader, raw))
for kind in ("directory", "fifo", "mode000", "symlink", "dangling_symlink"):
    setattr(EnvHarness, "test_file_type_" + kind, _file_type_case(kind))
for key in ("SENTINEL_POSTGRES_PASSWORD", "SHARADAR_API_KEY", "SENTINEL_BACKUP_DIR", "ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
    for index, value in enumerate((None, "", " ", "\t", "changeme", "replace-with-secret", "your_key_here", "<secret>", "...")):
        setattr(EnvHarness, "test_required_%s_%d" % (key, index), _missing_case(key, value))
for launcher in ("sentinel-compose.sh", "sentinel-autonomous-deploy.sh", "sentinel-go-validate.sh", "sentinel-bringup.sh"):
    for case in ("valid", "missing_file", "missing_required", "empty_override", "duplicate_conflict", "nul", "invalid_utf8", "unclosed_double", "control_in_comment"):
        setattr(EnvHarness, "test_launcher_%s_%s" % (launcher.replace('-', '_').replace('.', '_'), case), _shell_case(launcher, case))
for launcher in ("sentinel-compose.sh", "sentinel-autonomous-deploy.sh", "sentinel-go-validate.sh", "sentinel-bringup.sh") + MAINTENANCE_LAUNCHERS:
    for key in ("RUN", "PRODUCTION_RUN", "FORWARDED_ARGS", "LOCAL_FULL", "RUNTIME_POINTER",
                "CANONICAL", "BACKUP", "INITIALIZE_BACKUP", "record", "records",
                "SENTINEL_HOST_PYTHON", "SENTINEL_PYTHON", "SENTINEL_GO_LOCK_HELD",
                "SENTINEL_GO_RUN_TOKEN", "SENTINEL_DEPLOY_LOCK_FD",
                "SENTINEL_BASE_BACKUP_LOCK_HELD"):
        setattr(EnvHarness, "test_control_%s_%s" % (launcher.replace('-', '_').replace('.', '_'), key), _shell_control_case(launcher, key))
for launcher in MAINTENANCE_LAUNCHERS:
    for case in ("valid", "literal_override", "process_only", "empty_override",
                 "missing_SENTINEL_BACKUP_DIR", "missing_SENTINEL_POSTGRES_PASSWORD",
                 "missing_SENTINEL_PUBLICATION_RECEIPT_KEY", "duplicate_conflict",
                 "nul", "invalid_utf8", "unclosed_double", "control_in_comment"):
        setattr(EnvHarness, "test_maintenance_%s_%s" % (launcher.replace('-', '_').replace('.', '_'), case), _maintenance_case(launcher, case))
for key, lower, upper in (
        ("SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS", 30, 1800),
        ("SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS", 0, 1800),
        ("SENTINEL_AUTOMATION_HEARTBEAT_SECONDS", 1, 300),
        ("SENTINEL_DEPLOY_DATA_RETRY_SECONDS", 30, 3600),
        ("SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS", 300, 86400)):
    for index, value in enumerate((str(lower), str(upper), str(lower - 1), str(upper + 1), "", "NaN", "Inf", "1.0", "1e3", "9" * 5000)):
        setattr(EnvHarness, "test_numeric_%s_%d" % (key, index), _semantic_case(key, value, index < 2))
for key, values in {
    "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE": ("NaN", "Infinity", "-0.1", "1.1", "1.0", "0.0", "0.750", ""),
    "SENTINEL_FORCE_CPU_LIMITS": ("true", "false", "2", ""),
    "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED": ("true", "false", "2", ""),
    "SENTINEL_DEPLOY_ALLOW_EMPTY_BIND": ("tru", "2"),
    "SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY": ("tru", "2"),
    "SENTINEL_BACKUP_DIR": ("relative/path", "~/backup"),
    "ALPACA_BASE_URL": ("https://api.alpaca.markets", "https://paper-api.alpaca.markets.evil", "http://paper-api.alpaca.markets", ""),
    "SENTINEL_POSTGRES_PASSWORD": ("has@sign", "has:colon", "has/slash", "has#hash", "has%escape", "has?query", "has space"),
    "SENTINEL_PUBLICATION_RECEIPT_KEY": ("too-short", "replace-with-an-independent-long-random-value"),
    "SHARADAR_API_KEY": ("line\nbreak", "nul\0byte", "invisible\u200b", "control\x1b"),
}.items():
    for index, value in enumerate(values):
        setattr(EnvHarness, "test_semantic_%s_%d" % (key, index), _semantic_case(key, value, False))


if __name__ == "__main__":
    unittest.main()
