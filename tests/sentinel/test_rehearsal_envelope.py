"""Both entry paths authenticate. The coverage gate has a number in it.

TWO HOLES, both of the same kind: a check that exists on one path and not the
other, and a check that verifies a field is PRESENT rather than what it says.

```text
--from-json    skipped the run authentication entirely and went straight to
               reading `book_artifact`. A hand-written file with the right
               window and fabricated equivalence and reconciliation fields
               bypassed every check --run-id had just gained. A second
               entrance with weaker locks is not a second entrance.

coverage       `if cov is None: fail` proves the field exists. The historical
               failure being gated is EXACTLY a present-but-partial coverage:
               residual 0.00, both episode lists empty, and the cash bucket
               holding 3 of 8 episodes and $132k of $342k.
```
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "sentinel_rehearsal.py"
FINAL = ROOT / "scripts" / "sentinel-finalize-rehearsal.sh"

sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_rehearsal as R  # noqa: E402

START, END = "2021-01-04", "2023-12-29"


def envelope(**over):
    """NESTED: the row's claims at the top, the run's payload under `summary`.

    The image id is POPULATED here, deliberately. An earlier fixture set it to
    None and every test passed — which is how "a missing image id is a hole"
    stayed a comment rather than a rule."""
    env = {
        "schema": R.ENVELOPE_SCHEMA,
        "run_id": "abc", "status": "success", "mode": "chain_rehearsal",
        "spec": {"start_date": START, "end_date": END,
                 "retention_mode": "bounded",
                 "engine_identity": {
                     "wealth_core_source_hash": "a" * 64,
                     "bt_engine_app_source_hash": "b" * 64,
                     "python": "3.12.13",
                     "image_id": "sha256:" + "c" * 64,
                     "image_ref": "stocker-bt-engine:latest"}},
        "parity_hashes": {"final_result": "x"},
        "summary": {
            "book_artifact": {"schema": "stock_strategy_shared.book_artifact/1",
                              "window": {"start": START, "end": END},
                              "held": ["AAA"], "pending_terminal": []}},
    }
    env.update(over)
    return env


def run(tmp_path, env):
    p = tmp_path / "env.json"
    p.write_text(json.dumps(env))
    return R.authenticate(p, tmp_path / "book.json", START, END)


class TestOneValidatorForBothPaths:

    def test_a_well_formed_envelope_authenticates(self, tmp_path):
        assert run(tmp_path, envelope()) == 0
        assert json.loads((tmp_path / "book.json").read_text())["held"] == ["AAA"]

    def test_THE_FALSIFIER_a_hand_written_summary_is_REFUSED(self, tmp_path):
        """The --from-json bypass: the right book window and fabricated
        everything else. It used to reach the audit and the gates."""
        forged = {"book_artifact": envelope()["summary"]["book_artifact"],
                  "equivalence": {"state_hash_matches": True,
                                  "ledger_hash_matches": True,
                                  "final_cash_matches": True},
                  "terminal_reconciliation": {"unreconciled_episodes": [],
                                              "unexplained_episodes": [],
                                              "residual": 0.0,
                                              "cash_coverage_fraction": 1.0}}
        assert run(tmp_path, forged) == 1

    @pytest.mark.parametrize("field", list(R.REQUIRED))
    def test_every_REQUIRED_field_is_actually_required(self, tmp_path, field):
        env = envelope()
        env.pop(field)
        assert run(tmp_path, env) == 1, f"{field} was optional after all"

    def test_a_FAILED_run_is_refused(self, tmp_path):
        assert run(tmp_path, envelope(status="failed")) == 1

    def test_a_NON_CHAIN_mode_is_refused(self, tmp_path):
        assert run(tmp_path, envelope(mode="replay")) == 1

    def test_a_DIFFERENT_window_in_the_spec_is_refused(self, tmp_path):
        env = envelope()
        env["spec"]["end_date"] = "2022-12-30"
        assert run(tmp_path, env) == 1

    def test_a_DIFFERENT_window_in_the_BOOK_is_refused(self, tmp_path):
        env = envelope()
        env["summary"]["book_artifact"]["window"]["start"] = "2022-01-03"
        assert run(tmp_path, env) == 1

    def test_an_OLD_schema_is_refused_with_the_remedy(self, tmp_path, capsys):
        assert run(tmp_path, envelope(schema="old/0")) == 1
        assert "re-export" in capsys.readouterr().err

    def test_the_finalizer_uses_the_validator_on_BOTH_paths(self):
        body = FINAL.read_text()
        assert body.count("sentinel_rehearsal.py authenticate") == 1
        code = [l for l in body.splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        auth = next(i for i, l in enumerate(code) if "authenticate" in l)
        fi = next(i for i, l in enumerate(code) if 'if [ -n "${FROM_JSON}" ]' in l)
        assert auth > fi, "the validator runs inside a branch, not after both"

    def test_the_book_is_only_written_when_authentication_PASSES(self, tmp_path):
        run(tmp_path, envelope(status="failed"))
        assert not (tmp_path / "book.json").exists()


class TestTheEngineThatRanItIsRecorded:
    """A container cannot discover its own image, and inspecting a mutable
    `:latest` tag at finalization answers what the tag points at NOW — rebuild
    it between the run and this step and the manifest names the wrong image."""

    def test_a_MISSING_engine_identity_is_refused(self, tmp_path):
        env = envelope()
        env["spec"].pop("engine_identity")
        assert run(tmp_path, env) == 1

    def test_an_engine_identity_with_no_source_hash_is_refused(self, tmp_path):
        env = envelope()
        env["spec"]["engine_identity"] = {"python": "3.12.13"}
        assert run(tmp_path, env) == 1

    def test_bt_engine_RECORDS_it_at_run_start(self):
        src = (ROOT / "services" / "bt-engine" / "app"
               / "wealth_core_api.py").read_text()
        assert "_engine_identity()" in src
        assert 'spec_json["engine_identity"]' in src

    def test_the_finalizer_BINDS_it_to_the_certified_image(self):
        body = FINAL.read_text()
        assert "produced by a\\n" not in body
        assert "different engine than the one being certified" in body
        assert "bt_engine_identity is MISSING" in body

    def test_the_shared_hash_matches_sentinels_own(self):
        """Two implementations of one digest would drift, and the whole point
        is that bt-engine's answer is comparable with Sentinel's."""
        sys.path.insert(0, str(ROOT / "shared"))
        sys.path.insert(0, str(ROOT))
        from sentinel import identity as ident
        from stock_strategy_shared import identity_hashes as IH

        import stock_strategy_shared.wealth_core as wc
        root = Path(wc.__file__).resolve().parent
        assert IH.package_source_hash(root) == ident.source_hash(root)["hash"]
        assert IH.wealth_core_source_hash() == IH.package_source_hash(root)


class TestTheCoverageGateHasANumberInIt:

    def gate(self):
        body = FINAL.read_text()
        return body[body.index("cov = tr.get"):body.index("missing = [k for k")]

    def test_it_compares_against_1_0_not_merely_None(self):
        g = self.gate()
        assert "!= 1.0" in g, (
            "the gate only proves the field EXISTS — which is exactly the "
            "historical failure: residual 0.00, both lists empty, and 3 of 8 "
            "episodes inside the reconciliation")

    def test_THE_FALSIFIER_partial_coverage_blocks(self):
        """coverage 0.375 with residual 0 and both lists empty must BLOCK."""
        tr = {"cash_coverage_fraction": 0.375, "residual": 0.0,
              "unreconciled_episodes": [], "unexplained_episodes": [],
              "cash_settled_episodes": 3, "episodes": 8,
              "non_cash_episodes": 5, "non_cash_carried_notional": 210000.0}
        failures = []
        cov = tr.get("cash_coverage_fraction")
        if cov is None:
            failures.append("missing")
        elif float(cov) != 1.0:
            failures.append(f"coverage {cov}")
        assert failures, "the rule as written would have passed 3-of-8 coverage"

    def test_full_coverage_does_NOT_block(self):
        cov = 1.0
        assert not (cov is None or float(cov) != 1.0)

    def test_the_message_NAMES_the_shortfall(self):
        g = self.gate()
        assert "cash_settled_episodes" in g and "episodes" in g


# ── the ROW's claims cannot be overwritten by the RUN's payload ──────────────

class TestTheEnvelopeSeparatesClaimsFromPayload:
    """The export flattened the summary over the row fields with `**summary`,
    so a payload field named `status` or `mode` would overwrite what the
    database actually said. Today's ChainRehearsal carries neither, so nothing
    was wrong in practice — and the authentication boundary was defeated
    STRUCTURALLY, which is the kind of defect that waits for a field to be added
    rather than announcing itself."""

    def test_THE_FALSIFIER_a_summary_claiming_success_cannot_override_a_failed_row(
            self, tmp_path):
        env = envelope(status="failed")
        env["summary"]["status"] = "success"
        env["summary"]["mode"] = "chain_rehearsal"
        assert run(tmp_path, env) == 1, (
            "a payload field answered a question the ROW was supposed to answer")

    def test_a_summary_cannot_supply_a_missing_spec(self, tmp_path):
        env = envelope()
        env["spec"] = {}
        env["summary"]["spec"] = {"start_date": START, "end_date": END}
        assert run(tmp_path, env) == 1

    def test_a_summary_cannot_supply_parity_hashes(self, tmp_path):
        env = envelope(parity_hashes=None)
        env["summary"]["parity_hashes"] = {"final_result": "x"}
        assert run(tmp_path, env) == 1

    def test_the_export_NESTS_rather_than_merging(self):
        body = VALIDATOR.read_text()
        assert '"summary": summary or {}' in body
        assert "**(summary or {})" not in body, (
            "the payload is still flattened over the row's claims")

    def test_a_book_at_the_TOP_LEVEL_is_not_read(self, tmp_path):
        """Payload lives under `summary`. A top-level `book_artifact` is a file
        someone assembled, and it must not be mistaken for one the run
        produced."""
        env = envelope()
        env["book_artifact"] = env["summary"].pop("book_artifact")
        assert run(tmp_path, env) == 1

    def test_a_NON_OBJECT_summary_is_refused(self, tmp_path):
        assert run(tmp_path, envelope(summary="not an object")) == 1


class TestTheENGINEImageIsBound:
    """Two bt-engine containers can carry the same Wealth Core tree and
    different interpreters, dependencies, loader code and client libraries — and
    bt-engine is what reads the corpus and builds the rehearsal inputs."""

    def test_a_NULL_image_id_is_now_REFUSED(self, tmp_path):
        """The earlier fixture asserted `image_id: None` was valid, which
        contradicted the comment calling it a hole."""
        env = envelope()
        env["spec"]["engine_identity"]["image_id"] = None
        assert run(tmp_path, env) == 1

    def test_a_MISSING_app_source_hash_is_refused(self, tmp_path):
        env = envelope()
        env["spec"]["engine_identity"].pop("bt_engine_app_source_hash")
        assert run(tmp_path, env) == 1

    def test_the_refusal_NAMES_the_remedy(self, tmp_path, capsys):
        env = envelope()
        env["spec"]["engine_identity"]["image_id"] = None
        run(tmp_path, env)
        assert "bt-engine-up.sh" in capsys.readouterr().err

    def test_COMPOSE_injects_the_id(self):
        body = (ROOT / "docker-compose.backtest.yml").read_text()
        assert "BT_ENGINE_IMAGE_ID:" in body and "BT_ENGINE_IMAGE:" in body

    def test_the_launcher_builds_INSPECTS_then_starts(self):
        body = (ROOT / "scripts" / "bt-engine-up.sh").read_text()
        code = [l for l in body.splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
        build = next(i for i, l in enumerate(code) if "build bt-engine" in l)
        inspect = next(i for i, l in enumerate(code) if "image inspect" in l)
        up = next(i for i, l in enumerate(code) if "up -d --force-recreate" in l)
        assert build < inspect < up, (
            "the id must be read from the image that is about to run, not from "
            "whatever the tag pointed at before the build")

    def test_the_launcher_REFUSES_when_the_image_cannot_be_inspected(self):
        body = (ROOT / "scripts" / "bt-engine-up.sh").read_text()
        assert "REFUSED: could not inspect" in body and "exit 1" in body

    def test_an_ORDINARY_up_still_works_and_records_null(self):
        """Which the certification path refuses — so a rehearsal started the
        casual way cannot be certified by accident, only re-run."""
        body = (ROOT / "docker-compose.backtest.yml").read_text()
        assert "BT_ENGINE_IMAGE_ID: ${BT_ENGINE_IMAGE_ID:-}" in body

    def test_the_finalizer_COMPARES_recorded_against_certified(self):
        body = FINAL.read_text()
        assert "recorded != present" in body
        assert "did not produce these numbers" in body
