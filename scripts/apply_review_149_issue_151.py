from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one match in {path}, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "scripts/sentinel-emergency-kill.sh",
    '''[ -n "${SENTINEL_POSTGRES_PASSWORD:-}" ] || {
  echo "REFUSED: SENTINEL_POSTGRES_PASSWORD is required to reach the durable automation fence" >&2
  exit 2
}
''',
    '''# Do not preflight SENTINEL_POSTGRES_PASSWORD in the shell. Compose owns
# configuration resolution and may load it from the repository's normal .env;
# requiring it to be exported here recreates the emergency-path guard inversion
# this wrapper exists to remove.
''')

replace_once(
    "sentinel/panel/model.py",
    '''    if error:
        return Row("ownership", "Ownership", "UNREADABLE", UNKNOWN,
                   f"the canonical binding could not be read — {error}", at)
    if state in ("SENTINEL_OWNERSHIP_ESTABLISHED",
                 "WEALTH_CORE_BOOTSTRAP_ALLOWED"):
''',
    '''    if error:
        return Row("ownership", "Ownership", "UNREADABLE", UNKNOWN,
                   f"the canonical binding could not be read — {error}", at)

    # The panel source consumes OwnershipView.state.value directly. These are
    # the canonical database-backed ownership facts; never reinterpret them as
    # stages of the retired handover state machine.
    if state == "OWNED":
        return Row(
            "ownership", "Ownership", "SENTINEL OWNED", OK,
            "canonical PostgreSQL account binding establishes Sentinel "
            "ownership; see Broker for current positions", at)
    if state == "NOT_OWNED":
        return Row(
            "ownership", "Ownership", "NOT ESTABLISHED", WARN,
            "canonical PostgreSQL account binding is absent — Sentinel must "
            "not treat the account as owned", at)
    if state in (None, "UNKNOWN"):
        return Row(
            "ownership", "Ownership", "UNKNOWN", UNKNOWN,
            "canonical ownership state is unknown; no ownership authority is "
            "inferred from audit files", at)

    # Legacy vocabulary is retained only for old direct model callers. The
    # production panel source above never emits these strings; PostgreSQL's
    # OwnershipView enum is authoritative.
    if state in ("SENTINEL_OWNERSHIP_ESTABLISHED",
                 "WEALTH_CORE_BOOTSTRAP_ALLOWED"):
''')

Path("tests/sentinel/test_issue_149_151.py").write_text(r'''from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from sentinel import ownership_view
from sentinel.panel import model, sources


ROOT = Path(__file__).resolve().parents[2]


def test_149_emergency_wrapper_allows_password_only_in_dotenv(tmp_path):
    """The emergency wrapper must not require an exported DB password.

    Compose normally resolves SENTINEL_POSTGRES_PASSWORD from .env. Requiring
    shell export before invoking Compose would recreate #149's exact guard
    inversion during an emergency.
    """
    repo = ROOT / "repo"
    dotenv = repo / ".env"
    previous = dotenv.read_bytes() if dotenv.exists() else None
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    argv_file = tmp_path / "docker-argv"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$DOCKER_ARGV_FILE\"\n")
    docker.chmod(0o755)

    env = os.environ.copy()
    env.pop("SENTINEL_POSTGRES_PASSWORD", None)
    env.update({
        "PATH": f"{fakebin}:{env['PATH']}",
        "DOCKER_ARGV_FILE": str(argv_file),
        "SENTINEL_FORCE_CPU_LIMITS": "1",
    })
    try:
        dotenv.write_text("SENTINEL_POSTGRES_PASSWORD=fixture-only-in-dotenv\n")
        subprocess.run(
            ["bash", str(repo / "scripts/sentinel-emergency-kill.sh"),
             "--actor", "operator", "--reason", "emergency"],
            cwd=repo, env=env, check=True)
    finally:
        if previous is None:
            dotenv.unlink(missing_ok=True)
        else:
            dotenv.write_bytes(previous)

    argv = argv_file.read_text().splitlines()
    assert "--no-deps" in argv
    assert "engage-paper-automation-kill-switch" in argv
    assert "docker-compose.sentinel-backup.yml" not in " ".join(argv)
    assert "docker-compose.sentinel-automation.yml" not in " ".join(argv)


def _view(state: ownership_view.Ownership, detail: str = "fixture"):
    return ownership_view.OwnershipView(
        state=state, source="database", detail=detail)


def test_151_exact_owned_source_path_renders_green(monkeypatch):
    """Exercise sources.py's exact view.state.value -> ownership_row path."""
    monkeypatch.setattr(
        ownership_view, "read",
        lambda *_args, **_kwargs: _view(
            ownership_view.Ownership.OWNED,
            "bound to alpaca/PA3UVTMJYYGM at epoch 1"))

    row = sources._ownership(Path("/retired-audit-location"),
                             "postgresql://fixture")

    assert row.status is model.OK
    assert row.value == "SENTINEL OWNED"
    assert "part-way" not in row.detail
    assert "PostgreSQL" in row.detail


@pytest.mark.parametrize(
    ("state", "expected_status", "expected_value"),
    [
        (ownership_view.Ownership.NOT_OWNED, model.WARN, "NOT ESTABLISHED"),
        (ownership_view.Ownership.UNKNOWN, model.UNKNOWN, "UNREADABLE"),
    ],
)
def test_151_not_owned_and_unknown_remain_distinct(
        monkeypatch, state, expected_status, expected_value):
    monkeypatch.setattr(
        ownership_view, "read",
        lambda *_args, **_kwargs: _view(state, "canonical source detail"))

    row = sources._ownership(Path("/retired-audit-location"),
                             "postgresql://fixture")

    assert row.status is expected_status
    assert row.value == expected_value
    assert "part-way" not in row.detail


def test_151_model_does_not_treat_unknown_as_not_owned():
    unknown = model.ownership_row(state="UNKNOWN", at=None)
    not_owned = model.ownership_row(state="NOT_OWNED", at=None)

    assert unknown.status is model.UNKNOWN
    assert unknown.value == "UNKNOWN"
    assert not_owned.status is model.WARN
    assert not_owned.value == "NOT ESTABLISHED"
''')

print("applied #149 review fix and #151 panel fix")
