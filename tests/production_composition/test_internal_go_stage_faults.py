"""The E2E mutations must reach the selected call and preserve adjacent stages."""
from types import SimpleNamespace
from pathlib import Path

import pytest

from tools import production_go_stage_faults as faults


@pytest.mark.parametrize("name", [name for name, _ in faults.STAGES])
def test_selected_fault_keeps_unrelated_docker_commands_exact(name):
    argv = ["compose", "run", "sentinel", "-c", "print('unrelated readiness preflight')"]
    assert faults.docker_arguments(argv, name) == argv
    assert faults.docker_arguments(["image", "inspect", "sha256:abc"], name) == [
        "image", "inspect", "sha256:abc"]


def test_schema_fault_raises_at_the_actual_selected_call(monkeypatch, capsys):
    from sentinel import schema
    events = []
    monkeypatch.setattr(schema, "ensure_schema", lambda c: events.append("schema"))
    source = """
from sentinel import schema
marker = 'SENTINEL_GO_PREPARATION='
events.append('before schema')
schema.ensure_schema(None)
events.append('after schema')
"""
    argv = ["compose", "run", "sentinel", "-c", source]
    changed = faults.docker_arguments(argv, "schema-migration")
    with pytest.raises(RuntimeError, match="E2E_STAGE_FAULT:schema-migration"):
        exec(changed[-1], {"events": events})
    assert events == ["before schema"]
    assert "E2E_STAGE_FAULT:schema-migration" in capsys.readouterr().out
    assert argv[-1] == source


def test_publication_fault_preserves_catchup_then_refuses_final_check(capsys):
    source = """
marker = 'SENTINEL_GO_PREPARATION='
if True:
    events.append('catchup completed')
    phase = 'PUBLICATION_CHECK'
    events.append('publication accepted')
"""
    changed = faults.docker_arguments(["compose", "run", "-c", source], "publication-check")
    events = []
    with pytest.raises(RuntimeError, match="E2E_STAGE_FAULT:publication-check"):
        exec(changed[-1], {"events": events})
    assert events == ["catchup completed"]
    assert "E2E_STAGE_FAULT:publication-check" in capsys.readouterr().out


def test_host_evidence_fault_occurs_when_writer_is_called(monkeypatch, capsys):
    events = []
    writer = SimpleNamespace(write_zip_no_clobber=lambda: events.append("write"))
    def main():
        events.append("production preceding work")
        writer.write_zip_no_clobber()
        events.append("promotion")
    entry = SimpleNamespace(go=writer, main=main)
    monkeypatch.setattr(faults.importlib, "import_module", lambda _: entry)
    monkeypatch.setattr(faults.sys, "argv", [])
    monkeypatch.setattr(faults.sys, "path", list(faults.sys.path))
    with pytest.raises(RuntimeError, match="E2E_STAGE_FAULT:validation-evidence"):
        faults.python_main(["scripts/sentinel_go_verified_entry.py"], "validation-evidence")
    assert events == ["production preceding work"]
    assert "E2E_STAGE_FAULT:validation-evidence" in capsys.readouterr().out


def test_operational_fault_retains_canonical_parity_cli_arguments():
    original = ["compose", "run", "sentinel", "-m", "tools.sentinel_operational_parity",
                "--starting-cash", "100000", "--expected-commit", "a" * 40]
    changed = faults.docker_arguments(original, "operational-parity")
    assert changed[:3] == original[:3]
    assert changed[-4:] == original[-4:]
    assert "advance_session" in changed[4]
    assert "raise SystemExit(main())" in changed[4]
    compile(changed[4], "<parity-fault>", "exec")


@pytest.mark.parametrize("failure", [None, "same-version", "same-frontier", "wrong-subject"])
def test_success_requires_actual_publication_advance_bound_to_go(monkeypatch, failure):
    monkeypatch.syspath_prepend(str(Path(faults.__file__).parent))
    from tools import production_go_e2e_audit as audit
    seeded = {"version": 1, "visible_frontier": "2026-09-03",
              "publication_fingerprint": "a" * 64}
    published = {"version": 2, "visible_frontier": "2026-09-04",
                 "publication_fingerprint": "b" * 64}
    value = audit.go.data_publication_subject_value({
        key: published[key] for key in ("visible_frontier", "publication_fingerprint")})
    subject = audit.go._subject_digest("data_publication", value)
    if failure == "same-version":
        published["version"] = 1
    elif failure == "same-frontier":
        published["visible_frontier"] = seeded["visible_frontier"]
    elif failure == "wrong-subject":
        subject = "c" * 64
    if failure:
        with pytest.raises(audit.AuditFailure, match="publish|publication"):
            audit._assert_publication_advance(seeded, published, subject)
    else:
        audit._assert_publication_advance(seeded, published, subject)
