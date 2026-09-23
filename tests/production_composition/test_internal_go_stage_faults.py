"""The E2E mutations must reach the selected call and preserve adjacent stages."""
from types import SimpleNamespace
from pathlib import Path
import ast

import pytest

from tools import production_go_stage_faults as faults


def test_campaigns_cover_each_internal_stage_once():
    combined = tuple(stage for group in ("preparation", "financial", "handoff")
                     for stage in faults.selected_stages(group))
    assert combined == faults.STAGES
    assert len(combined) == len({name for name, _ in combined}) == 11
    assert faults.selected_stages("operator") == ()
    with pytest.raises(ValueError, match="unknown GO sensitivity group"):
        faults.selected_stages("partial")


@pytest.mark.parametrize("name", [name for name, _ in faults.STAGES])
def test_injected_fault_remains_visible_through_production_redaction(name):
    from scripts.sentinel_go_probe_contract import safe_detail
    marker = "E2E_STAGE_FAULT:" + name
    assert safe_detail(marker) == marker


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


@pytest.mark.parametrize("fault,attribute", [
    ("feed-catchup", "prepare"), ("sharadar-readiness", "readiness")])
def test_rolling_fault_reaches_the_production_call_site(monkeypatch, capsys, fault, attribute):
    monkeypatch.syspath_prepend(str(Path(faults.__file__).parents[1] / "scripts"))
    from sentinel.feed import rolling_go_inputs
    from scripts import sentinel_go_24x7_entry as preparation
    from scripts import sentinel_go_validate as go

    source = preparation._PREPARATION_CODE if fault == "feed-catchup" else go._READINESS_CODE
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and isinstance(node.func.value, ast.Name)
             and node.func.value.id == "rolling_go_inputs" and node.func.attr == attribute]
    assert len(calls) == 1
    marker = "SENTINEL_GO_PREPARATION=" if fault == "feed-catchup" else "SENTINEL_GO_READINESS="
    witness = f"marker = {marker!r}\n" + ast.unparse(calls[0])
    reached = []
    monkeypatch.setattr(rolling_go_inputs, attribute, lambda *_a, **_k: reached.append("healthy"))
    namespace = dict(rolling_go_inputs=rolling_go_inputs, c=None, target="2026-09-22")
    exec(witness, namespace)
    assert reached == ["healthy"]
    changed = faults.docker_arguments(["compose", "run", "-c", witness], fault)
    with pytest.raises(RuntimeError, match="E2E_STAGE_FAULT:" + fault):
        exec(changed[-1], namespace)
    assert reached == ["healthy"]
    assert "E2E_STAGE_FAULT:" + fault in capsys.readouterr().out


def test_positive_campaign_cannot_claim_sensitivity(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(faults.__file__).parent))
    from tools import production_go_e2e_audit as audit
    monkeypatch.setattr(audit.base, "_git_head", lambda: pytest.fail("invalid campaign reached GO setup"))
    with pytest.raises(audit.AuditFailure, match="cannot claim sensitivity"):
        audit.run(output=tmp_path / "evidence.json", sensitivity=True, sensitivity_group="positive")
    assert not (tmp_path / "evidence.json").exists()


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
