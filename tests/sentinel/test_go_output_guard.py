from __future__ import annotations

import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


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


def test_openfigi_key_is_redacted_as_an_actual_secret():
    key = 'private-mapping-token'
    values = guard._secret_values({'OPENFIGI_API_KEY':key})
    assert key in values
    assert key not in guard.redact('lookup failed: '+key, secrets=values)


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


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM, signal.SIGKILL])
def test_child_signal_exit_is_normalized_for_shell(monkeypatch, signum):
    monkeypatch.setattr(guard.go, "merged_environment", lambda: {})
    assert guard.run_guarded([
        sys.executable, "-c",
        "import os,signal; signal.signal(signal.SIGINT, signal.SIG_DFL); "
        "os.kill(os.getpid(), %d)" % signum,
    ]) == 128 + signum


def test_webhook_is_redacted_from_streams_and_scanned_in_bundles(monkeypatch, capsys):
    secret = "https://alerts.example.invalid/private-webhook-canary-346"
    configured = {"SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL": secret}
    monkeypatch.setattr(guard.go, "merged_environment", lambda: configured)
    rc = guard.run_guarded([
        sys.executable, "-c",
        "import sys; print(%r); print(%r, file=sys.stderr)" % (secret, secret),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert "[REDACTED]" in captured.out
    assert "[REDACTED]" in captured.err
    assert secret.encode() in guard.go.secret_candidates(configured, {})


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


def test_signal_arriving_during_child_start_is_forwarded_after_spawn(monkeypatch):
    sent = []

    class FakePopen:
        def __init__(self, *_args, **_kwargs):
            self.pid = 12345
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            signal.raise_signal(signal.SIGTERM)

        def wait(self):
            return 143

    monkeypatch.setattr(guard.go, "merged_environment", lambda: {})
    monkeypatch.setattr(guard.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        guard, "_send_process_group", lambda _proc, signum: sent.append(signum))
    monkeypatch.setattr(guard, "_escalate_process_group", lambda _proc: None)
    assert guard.run_guarded(["synthetic-child"]) == 143
    assert sent == [signal.SIGTERM]


def test_signal_during_output_drain_waits_for_descendant_escalation(monkeypatch):
    joined = []
    sent = []

    class FakePopen:
        pid = 12345
        stdout = io.StringIO("")
        stderr = io.StringIO("")
        def __init__(self, *_a, **_kw):
            pass
        def wait(self):
            return 0  # Leader exited; descendants may still hold the pipes.

    class ControlledThread:
        def __init__(self, *, target, **_kw):
            self.target = target
        def start(self):
            pass
        def join(self, **_kw):
            joined.append(self.target.__name__)
            if not sent:
                signal.raise_signal(signal.SIGTERM)

    monkeypatch.setattr(guard.go, "merged_environment", lambda: {})
    monkeypatch.setattr(guard.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(guard.threading, "Thread", ControlledThread)
    monkeypatch.setattr(guard, "_send_process_group", lambda _p, sig: sent.append(sig))
    assert guard.run_guarded(["controlled-child"]) == 143
    assert "_escalate_process_group" in joined


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


def test_exited_owner_does_not_leave_descendants_for_full_cleanup_grace(monkeypatch):
    sent = []
    fake = type("FakeProc", (), {"pid": 12345, "poll": lambda _: 0})()
    monkeypatch.setattr(guard, "_process_group_alive", lambda _proc: True)
    monkeypatch.setattr(guard, "_send_process_group", lambda _proc, sig: sent.append(sig))
    monkeypatch.setattr(guard.time, "sleep", lambda _: pytest.fail(
        "exited owner left descendants waiting for cleanup grace"))
    guard._escalate_process_group(fake)
    assert sent == [signal.SIGKILL]


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_cancellation_is_not_success_when_child_exits_zero(tmp_path, signum):
    ready = tmp_path / "ready"
    child = (
        "import pathlib,signal,sys,time; "
        "signal.signal(signal.SIGINT, lambda *_: sys.exit(0)); "
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
        "pathlib.Path(%r).touch(); time.sleep(30)" % str(ready)
    )
    proc = subprocess.Popen([
        sys.executable, str(SCRIPT_DIR / "sentinel_go_output_guard.py"),
        sys.executable, "-c", child,
    ], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert proc.poll() is None, proc.communicate()
            assert time.monotonic() < deadline, "child never became ready"
            time.sleep(0.02)
        proc.send_signal(signum)
        out, err = proc.communicate(timeout=10)
        assert proc.returncode == 128 + signum, (out, err)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_supported_launcher_guards_verified_go_diagnostics():
    source = (SCRIPT_DIR / "sentinel-go-validate.sh").read_text(encoding="utf-8")
    assert '"$PYTHON" scripts/sentinel_go_readonly_data_preflight.py' not in source
    assert (
        '"$PYTHON" scripts/sentinel_go_output_guard.py \\\n'
        '  "$PYTHON" scripts/sentinel_go_verified_entry.py "$@"'
    ) in source
