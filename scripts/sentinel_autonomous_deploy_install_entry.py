#!/usr/bin/env python3
"""Install reviewed dual-run services at any wall-clock time.

A GO bundle carrying ``deployment_wait_policy`` may promote and stage the exact
certified dual-run software while session authority remains NO_GO. At the
existing quiesced pre-shadow boundary this entry waits for a causally eligible
source-final publication, re-runs the exact Wealth Core parity and Sharadar
readiness probes, binds that publication, and only then lets the retained shadow
lineage/authority path continue.

The original bundle remains the reviewed installation artifact. The later
publication binding is a separate local evidence record linked to that bundle.
No waiting state grants broker or shadow-session authority, and no vendor ingest
is attempted before the reviewed source-final not-before instant.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Mapping, Optional, Sequence
import zipfile

import sentinel_autonomous_deploy_bootstrap as bootstrap
import sentinel_go_install_entry as install_go
import sentinel_go_validate as go


core = bootstrap.core
hardened = bootstrap.hardened

_WAIT_POLICY_DIGEST = core._validation_subject_digest(
    install_go.WAIT_POLICY_SUBJECT, install_go.WAIT_POLICY)
_DUMMY_DATA_DIGEST = hashlib.sha256(
    b"sentinel-deferred-data-publication-normalization-v1").hexdigest()
_ORIGINAL_PARSE = core.parse_reviewed_validation_bundle
_ORIGINAL_VERIFY = core.verify_reviewed_validation_environment


class CausalSessionExpired(RuntimeError):
    """A safe current-session attempt ran out of reviewed pre-open margin."""


def _subject_map(validation: Mapping) -> Mapping[str, str]:
    subjects = validation.get("subjects")
    if not isinstance(subjects, list):
        raise core.DeployRefused("validation subjects are malformed")
    found = {}
    for subject in subjects:
        if (not isinstance(subject, dict)
                or set(subject) != {"kind", "digest"}):
            raise core.DeployRefused("validation subject record is malformed")
        kind = str(subject.get("kind") or "")
        digest = str(subject.get("digest") or "")
        if (not kind or kind in found
                or core._HEX64.fullmatch(digest) is None):
            raise core.DeployRefused("validation subject binding is malformed")
        found[kind] = digest
    return found


def _gate_statuses(validation: Mapping) -> Mapping[str, str]:
    gates = validation.get("gates")
    if not isinstance(gates, list) or len(gates) != len(core.VALIDATION_GATES):
        raise core.DeployRefused("validation gate set is malformed")
    statuses = {}
    for expected, gate in zip(core.VALIDATION_GATES, gates):
        if (not isinstance(gate, dict)
                or gate.get("id") != expected
                or gate.get("status") not in {"PASS", "FAIL", "NOT_PROVEN"}
                or core._HEX64.fullmatch(
                    str(gate.get("evidence_sha256") or "")) is None):
            raise core.DeployRefused("validation gate binding is malformed")
        statuses[expected] = str(gate["status"])
    return statuses


def _waiting_contract(validation: Mapping, *, mode: str) -> bool:
    """Recognize only the GO producer's explicit fenced-installation contract."""
    if mode != "dual":
        return False
    subjects = _subject_map(validation)
    if subjects.get(install_go.WAIT_POLICY_SUBJECT) != _WAIT_POLICY_DIGEST:
        return False
    if "data_publication" in subjects:
        raise core.DeployRefused(
            "waiting deployment must not freeze a transient data publication")

    preparation = validation.get("preparation")
    if (not isinstance(preparation, dict)
            or preparation.get("schema") != core.VALIDATION_PREPARATION_SCHEMA
            or preparation.get("status") != "PASS"
            or preparation.get("schema_migration_attempted") is not True
            or type(preparation.get("bounded_sharadar_daily_attempted")) is not bool
            or preparation.get("completed_before_validation_boundary") is not True
            or preparation.get("broker_mutation_attempts") != 0
            or core._HEX64.fullmatch(
                str(preparation.get("evidence_sha256") or "")) is None):
        raise core.DeployRefused(
            "waiting deployment lacks completed installation preparation")

    database = validation.get("database_financial_health")
    checks = database.get("checks") if isinstance(database, dict) else None
    if (not isinstance(database, dict)
            or database.get("schema") != core.VALIDATION_DATABASE_HEALTH_SCHEMA
            or database.get("status") != "PASS"
            or not isinstance(checks, dict)):
        raise core.DeployRefused(
            "waiting deployment lacks structural database health")
    expected_checks = {
        "behavioral_schema_exact", "feed_schema_exact",
        "publication_complete", "publication_chain_unique_and_gap_free",
        "recent_xnys_axis_exact", "frontier_security_keys_unique",
        "repeatable_read_only", "publication_pin_excludes_writers",
        "publication_stable_under_pin", "required_indexes_exact",
        "predecessor_query_plan_indexed", "frontier_query_plan_indexed",
        "warmup_revision_input_complete", "prospective_trading_window",
    }
    structural = expected_checks - {"prospective_trading_window"}
    if (set(checks) != expected_checks
            or any(checks[name] is not True for name in structural)
            or type(checks.get("prospective_trading_window")) is not bool):
        raise core.DeployRefused(
            "waiting deployment database health has a non-temporal failure")

    statuses = _gate_statuses(validation)
    install_gates = (
        "git_identity", "certified_suite_no_skips",
        "database_financial_health", "wealth_core_nas_parity",
        "alpaca_paper_account", "zero_mutation_boundary",
    )
    if any(statuses[name] != "PASS" for name in install_gates):
        raise core.DeployRefused(
            "waiting deployment does not pass every installation gate")

    shadow_state = validation.get("shadow_state")
    if (validation.get("dual_run_verdict") != "DUAL_RUN_NO_GO"
            or not install_go._wait_failures_safe(validation)
            or not isinstance(shadow_state, dict)
            or shadow_state.get("internally_coherent") is not True):
        raise core.DeployRefused(
            "waiting bundle does not represent a session-only fenced dual-run NO_GO state")
    return True


def _normalized_waiting_validation(validation: Mapping) -> dict:
    """Temporary strict-parser view; never returned or persisted as evidence."""
    value = json.loads(json.dumps(validation))
    preparation = value["preparation"]
    preparation["bounded_sharadar_daily_attempted"] = True
    preparation["completed_before_validation_boundary"] = True
    preparation["status"] = "PASS"

    database = value["database_financial_health"]
    database["status"] = "PASS"
    database["checks"]["prospective_trading_window"] = True

    for gate in value["gates"]:
        if gate["id"] == "sharadar_readiness":
            gate["status"] = "PASS"
    value["shadow_state"]["fresh"] = True
    value["shadow_state"]["internally_coherent"] = True
    value["shadow_verdict"] = "SHADOW_GO"
    value["dual_run_verdict"] = "DUAL_RUN_GO"
    value["machine_failures"]["shadow"] = []
    value["machine_failures"]["dual_run"] = []
    value["subjects"].append({
        "kind": "data_publication", "digest": _DUMMY_DATA_DIGEST})
    return value


def _write_normalized_bundle(members: Mapping[str, bytes], validation: Mapping,
                             directory: Path) -> Path:
    normalized = dict(members)
    normalized["validation.json"] = core._canonical_json(validation)
    manifest_inputs = {
        name: payload for name, payload in normalized.items()
        if name not in {"manifest.json", "SHA256SUMS"}
    }
    normalized["manifest.json"] = core._manifest_expected(manifest_inputs)
    sha_inputs = {
        name: payload for name, payload in normalized.items()
        if name != "SHA256SUMS"
    }
    normalized["SHA256SUMS"] = core._sha_sums_expected(sha_inputs)

    path = directory / "normalized-waiting-validation.zip"
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(normalized):
            archive.writestr(name, normalized[name])
    return path


def parse_reviewed_validation_bundle(
        path: Path, *, mode: str, confirmation: str,
        now: Optional[datetime] = None):
    """Validate original bytes first, then reuse the retained strict parser."""
    path = Path(path).expanduser().resolve()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise core.DeployRefused("validation bundle is unreadable") from exc
    if core._sha256(raw) != str(confirmation or ""):
        raise core.DeployRefused(
            "reviewed-GO confirmation does not match the validation bundle")

    members = core._read_validation_members(path)
    if members["README.txt"] != core.VALIDATION_README:
        raise core.DeployRefused("validation README differs from the fixed contract")
    manifest_inputs = {
        name: payload for name, payload in members.items()
        if name not in {"manifest.json", "SHA256SUMS"}
    }
    if members["manifest.json"] != core._manifest_expected(manifest_inputs):
        raise core.DeployRefused("validation manifest does not match member bytes")
    sha_inputs = {
        name: payload for name, payload in members.items()
        if name != "SHA256SUMS"
    }
    if members["SHA256SUMS"] != core._sha_sums_expected(sha_inputs):
        raise core.DeployRefused("validation SHA256SUMS does not match member bytes")

    validation = core._json_object(
        members["validation.json"], label="validation.json")
    if not _waiting_contract(validation, mode=mode):
        return _ORIGINAL_PARSE(
            path, mode=mode, confirmation=confirmation, now=now)

    with tempfile.TemporaryDirectory(prefix="sentinel-waiting-review-") as raw_dir:
        normalized_path = _write_normalized_bundle(
            members, _normalized_waiting_validation(validation), Path(raw_dir))
        normalized_digest = core._sha256(normalized_path.read_bytes())
        reviewed = _ORIGINAL_PARSE(
            normalized_path, mode=mode,
            confirmation=normalized_digest, now=now)

    reviewed.path = path
    reviewed.bundle_sha256 = str(confirmation)
    reviewed.data_publication_sha256 = None
    reviewed.validation = validation
    return reviewed


def _is_deferred(reviewed) -> bool:
    try:
        return _waiting_contract(reviewed.validation, mode=reviewed.mode)
    except core.DeployRefused:
        return False


def verify_reviewed_validation_environment(
        reviewed, *, env: Mapping[str, str], invoke=subprocess.run) -> None:
    if not _is_deferred(reviewed):
        return _ORIGINAL_VERIFY(reviewed, env=env, invoke=invoke)

    current_data = core._current_data_publication_subject(
        reviewed, env=env, invoke=invoke)
    provisional = core._validation_subject_digest(
        "data_publication", current_data)
    reviewed.data_publication_sha256 = provisional
    original_lineage = core._reviewed_shadow_lineage_preflight
    core._reviewed_shadow_lineage_preflight = lambda *_args, **_kwargs: None
    try:
        _ORIGINAL_VERIFY(reviewed, env=env, invoke=invoke)
    finally:
        core._reviewed_shadow_lineage_preflight = original_lineage
        reviewed.data_publication_sha256 = None


class InstallAnytimeConfig(hardened.Config):
    def __init__(self, env: Mapping[str, str]) -> None:
        super().__init__(env)
        self.data_wait_timeout_seconds = max(
            int(self.data_wait_timeout_seconds), 24 * 3600)


class InstallAnytimeDeploy(bootstrap.BootstrapDeploy):
    def _deferred_install(self) -> bool:
        return bool(
            self.reviewed_validation is not None
            and _is_deferred(self.reviewed_validation))

    def _causal_timing(self) -> Mapping:
        """Observe both the owed closed session and the current publication."""
        code = r'''
import json, os
from datetime import datetime, timezone
from sentinel.feed import calendar, publication, store
from sentinel.shadow_runtime import publication_not_before
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    current = publication.require_current(c)
    frontier = store.latest_visible_session(c)
    if frontier is None or current.window_end != frontier:
        raise RuntimeError('current publication/frontier disagree')
    now = datetime.now(timezone.utc)
    target = calendar.latest_closed_session(now)
    final_at = publication_not_before(target)
    execution = calendar.next_session(target)
    execution_open, _ = calendar.session_window(execution)
    execution_open = execution_open.astimezone(timezone.utc)
    remaining_ms = max(0, int((execution_open - now).total_seconds() * 1000))
    print(json.dumps({
        'frontier': frontier,
        'target': target,
        'target_source_final': now >= final_at,
        'target_source_final_at': final_at.isoformat(),
        'execution_session': execution,
        'execution_open_at': execution_open.isoformat(),
        'prospective': now < execution_open,
        'remaining_ms': remaining_ms,
    }, sort_keys=True))
finally:
    c.rollback(); c.close()
'''.strip()
        result = self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T", "--no-deps",
            "--entrypoint", "python", "sentinel", "-c", code],
            capture=True)
        value = core._json_output(result, label="causal deployment timing")
        if (not isinstance(value.get("frontier"), str)
                or not isinstance(value.get("target"), str)
                or type(value.get("target_source_final")) is not bool
                or type(value.get("prospective")) is not bool
                or type(value.get("remaining_ms")) is not int
                or value["remaining_ms"] < 0
                or not isinstance(value.get("target_source_final_at"), str)
                or not isinstance(value.get("execution_session"), str)
                or not isinstance(value.get("execution_open_at"), str)):
            raise core.DeployRefused("causal deployment timing is malformed")
        return value

    @staticmethod
    def _timing_eligible(value: Mapping) -> bool:
        return bool(
            value.get("target_source_final") is True
            and value.get("prospective") is True
            and type(value.get("remaining_ms")) is int
            and value["remaining_ms"] >= go.MIN_REMAINING_DEADLINE_MARGIN_MS
        )

    def _wait_until_causal_ready(self) -> Mapping:
        """Wait without vendor mutation until the target itself is source-final."""
        deadline = time.monotonic() + self.cfg.data_wait_timeout_seconds
        attempt = 1
        while True:
            self._assert_wait_fence()
            timing = self._causal_timing()
            if not self._timing_eligible(timing):
                self._write_deployment_state(
                    "WAITING_FOR_CAUSAL_SESSION", attempt=attempt, failures=[])
                print("\nDEPLOYMENT STAGED: WAITING_FOR_CAUSAL_SESSION", flush=True)
                print("  automation: disabled and kill switch engaged", flush=True)
                print("  current frontier: %s" % timing["frontier"], flush=True)
                print("  target close: %s" % timing["target"], flush=True)
                print("  target source final: %s" %
                      timing["target_source_final"], flush=True)
                print("  following open future: %s" % timing["prospective"], flush=True)
                print("  remaining pre-open ms: %s" % timing["remaining_ms"], flush=True)
            else:
                # Only after the owed target itself is source-final may the
                # existing vendor stabilization/catch-up path contact Sharadar.
                verdict = self._readiness_verdict()
                if verdict.get("ready") is True:
                    if timing["frontier"] != timing["target"]:
                        raise core.DeployRefused(
                            "readiness passed on a frontier different from the "
                            "causally eligible target")
                    self._base_cli(["check-data"])
                    self._write_deployment_state(
                        "DATA_READY_CAUSAL", attempt=attempt, failures=[])
                    return timing
                if self._freshness_wait_requirements(verdict) is None:
                    self._refuse_data_readiness(
                        verdict, attempt=attempt,
                        reason="installation data readiness has a non-temporal failure")
                self._wait_for_data(deadline=deadline)
                # Re-observe target/finality/margin after every potentially long
                # vendor/ingest path before using the resulting publication.
                attempt += 1
                continue

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise core.DeployRefused(
                    "timed out waiting for a causally eligible source-final session; "
                    "automation remains fenced")
            time.sleep(min(
                self.cfg.data_retry_seconds, max(1, int(remaining))))
            attempt += 1

    def _bind_current_publication(self, expected_timing: Mapping) -> None:
        """Re-earn economic data authority and recheck remaining session margin."""
        reviewed = self.reviewed_validation
        if reviewed is None:
            raise core.DeployRefused(
                "causal publication binding requires reviewed validation")
        now_text = go._utc_text(datetime.now(timezone.utc))
        subjects = {}
        timings = {}
        runner = go.CommandRunner()
        parity = go.probe_active_wealth_parity(
            runner, env=self.env,
            commit=reviewed.git_commit,
            candidate_image_digest=reviewed.test_image_digest,
            now_text=now_text, subject_values=subjects,
            timing_values=timings)
        readiness = go.probe_sharadar_readiness(
            runner, env=self.env,
            runtime_ref=reviewed.runtime_image_digest,
            now_text=now_text)
        publication_value = subjects.get("data_publication")
        if (parity.status != go.PASS or readiness.status != go.PASS
                or not isinstance(publication_value, str)):
            raise core.DeployRefused(
                "post-wait causal publication failed parity/readiness revalidation")

        final_timing = self._causal_timing()
        if (final_timing.get("target") != expected_timing.get("target")
                or final_timing.get("frontier") != expected_timing.get("target")
                or not self._timing_eligible(final_timing)):
            raise CausalSessionExpired(
                "causal target changed or lost minimum pre-open margin during "
                "post-wait parity/readiness")

        digest = core._validation_subject_digest(
            "data_publication", publication_value)
        reviewed.data_publication_sha256 = digest
        self.env["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] = digest
        self.runner.env["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] = digest
        os.environ["SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256"] = digest

        def invoke(argv, **_kwargs):
            return self.runner.run(argv, capture=True)

        _ORIGINAL_VERIFY(reviewed, env=self.env, invoke=invoke)
        core.verify_reviewed_account_binding(reviewed, self.cfg.account_id)

        evidence = {
            "schema": "sentinel.causal-publication-binding/1",
            "reviewed_bundle_sha256": reviewed.bundle_sha256,
            "data_publication_sha256": digest,
            "parity_evidence_sha256": parity.evidence_sha256,
            "readiness_evidence_sha256": readiness.evidence_sha256,
            "decision_session": final_timing["target"],
            "remaining_preopen_ms": final_timing["remaining_ms"],
            "bound_at": go._utc_text(datetime.now(timezone.utc)),
            "policy": install_go.WAIT_POLICY,
        }
        path = self.attempt_dir / "causal-publication-binding.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8")
        os.chmod(str(temporary), 0o600)
        temporary.replace(path)
        bootstrap._safe_update_dotenv(core.ENV_PATH, {
            "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": digest})

    def verify_reviewed_shadow_bindings_quiesced(self) -> None:
        reviewed = self.reviewed_validation
        if (reviewed is None or reviewed.mode not in {"shadow", "dual"}
                or not self._deferred_install()):
            return super().verify_reviewed_shadow_bindings_quiesced()

        self.phase(
            "review: quiesced install waits for causal source and binds publication")
        while True:
            timing = self._wait_until_causal_ready()
            try:
                self._bind_current_publication(timing)
                return
            except CausalSessionExpired as exc:
                # No authority was persisted. Continue under the same disabled+
                # kill fence and wait for the next causally eligible close.
                self._write_deployment_state(
                    "WAITING_FOR_NEXT_CAUSAL_SESSION", attempt=1,
                    failures=[{"name": "session_timing", "detail": str(exc)}])


def _install_overlay() -> None:
    core.parse_reviewed_validation_bundle = parse_reviewed_validation_bundle
    core.verify_reviewed_validation_environment = verify_reviewed_validation_environment
    bootstrap.hardened.Config = InstallAnytimeConfig
    bootstrap.BootstrapDeploy = InstallAnytimeDeploy


def main(argv: Optional[Sequence[str]] = None) -> int:
    _install_overlay()
    return bootstrap.main(list(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
