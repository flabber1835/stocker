from __future__ import annotations

import os
from pathlib import Path
import sys


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
