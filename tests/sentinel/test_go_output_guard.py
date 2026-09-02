from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_output_guard as guard


def test_redact_removes_bare_and_embedded_actual_secret_values():
    secret = "s3cr3t-value-with-no-keyword"
    text = "bare=%s embedded=prefix-%s-suffix\n" % (secret, secret)
    safe = guard.redact(text, secrets=(secret,))
    assert secret not in safe
    assert safe.count("[REDACTED]") == 2


def test_run_guarded_redacts_actual_secrets_on_stdout_and_stderr(monkeypatch, capsys):
    secret = "actual-runtime-authority-928374"
    monkeypatch.setattr(
        guard.go,
        "merged_environment",
        lambda: {
            "SHARADAR_API_KEY": secret,
            "SENTINEL_POSTGRES_PASSWORD": "",
        },
    )
    code = (
        "import sys; "
        "print(%r); "
        "print('ordinary text containing %s here' %% %r, file=sys.stderr)"
        % (secret, "%s", secret)
    )
    rc = guard.run_guarded([sys.executable, "-c", code])
    assert rc == 0
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    assert "[REDACTED]" in captured.out
    assert "[REDACTED]" in captured.err


def test_run_guarded_preserves_child_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(guard.go, "merged_environment", lambda: {})
    rc = guard.run_guarded([
        sys.executable,
        "-c",
        "import sys; print('typed refusal', file=sys.stderr); sys.exit(23)",
    ])
    assert rc == 23
    assert "typed refusal" in capsys.readouterr().err


def test_output_guard_preserves_exact_inherited_lifecycle_lock_descriptor():
    child = (
        "import sys; "
        "sys.path.insert(0, 'scripts'); "
        "import sentinel_go_lock as lock; "
        "print('LOCK_PROVEN' if lock.lifecycle_lock_is_held() else 'LOCK_MISSING'); "
        "sys.exit(0 if lock.lifecycle_lock_is_held() else 23)"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentinel_go_lock.py"),
            sys.executable,
            str(SCRIPT_DIR / "sentinel_go_output_guard.py"),
            sys.executable,
            "-c",
            child,
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert "LOCK_PROVEN" in completed.stdout
    assert "LOCK_MISSING" not in completed.stdout


def test_stale_lock_environment_refuses_before_child_start(monkeypatch, capsys):
    monkeypatch.setattr(guard.go, "merged_environment", lambda: {})
    monkeypatch.setenv(guard.go_lock.LOCK_HELD_ENV, "1")
    monkeypatch.setenv(guard.go_lock.LOCK_FD_ENV, "999999")
    rc = guard.run_guarded([
        sys.executable, "-c", "raise SystemExit('child must not start')"])
    assert rc == 2
    assert "lifecycle lock authority unavailable" in capsys.readouterr().err


def test_output_guard_forwards_termination_to_child_process_group(tmp_path):
    survived = tmp_path / "grandchild-survived"
    grandchild = (
        "import pathlib,time; "
        "time.sleep(1.0); "
        "pathlib.Path(%r).write_text('survived', encoding='utf-8'); "
        "time.sleep(30)" % str(survived)
    )
    child = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable, '-c', %r]); "
        "print('TREE_READY', flush=True); "
        "time.sleep(30)" % grandchild
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT_DIR / "sentinel_go_output_guard.py"),
            sys.executable,
            "-c",
            child,
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "TREE_READY"
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
        time.sleep(1.2)
        assert not survived.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_process_group_escalation_uses_sigkill_after_grace(monkeypatch):
    sent = []
    fake = type("FakeProc", (), {"pid": 12345})()
    monkeypatch.setattr(guard, "_TERMINATION_GRACE_SECONDS", 0.0)
    monkeypatch.setattr(guard, "_process_group_alive", lambda _proc: True)
    monkeypatch.setattr(
        guard, "_send_process_group", lambda _proc, signum: sent.append(signum))
    guard._escalate_process_group(fake)
    assert sent == [signal.SIGKILL]


def test_supported_launcher_guards_both_sensitive_diagnostic_surfaces():
    source = (SCRIPT_DIR / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    assert (
        '"$PYTHON" scripts/sentinel_go_output_guard.py \\\n'
        '    "$PYTHON" scripts/sentinel_go_readonly_data_preflight.py'
    ) in source
    assert (
        '"$PYTHON" scripts/sentinel_go_output_guard.py \\\n'
        '  "$PYTHON" scripts/sentinel_go_verified_entry.py "$@"'
    ) in source
