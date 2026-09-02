#!/usr/bin/env python3
"""Supported phased GO entry with fresh final volatile-account evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import subprocess
import sys
from typing import Optional, Sequence

import sentinel_go_lock as go_lock
import sentinel_go_observability as observability
import sentinel_go_phase_entry as phase
import sentinel_go_probe_contract as probe_contract

controller = phase.controller
go = controller.go
_ORIGINAL_PHASED = controller.run_phased_probes


class DeploymentCompatibleDatabaseHealthView(phase.StrictDatabaseHealthView):
    """Enforce fresh margin without silently changing the public bundle schema.

    The autonomous deployment parser intentionally requires the exact v1
    database-health field set. Fresh wall-clock margin is enforced through
    ``complete`` and by the bundle ``valid_until`` cap in phase_entry; adding a
    new top-level field here would make an otherwise valid GO bundle
    undeployable.
    """

    def to_dict(self) -> dict:
        return dict(self.base.to_dict())


def _final_account_probe(*, env, urlopen=None):
    mutation_counter = [0]
    gate, subjects = go.probe_alpaca_account(
        env=env,
        now_text=go._utc_text(datetime.now(timezone.utc)),
        urlopen=(urlopen or go.urllib.request.urlopen),
        mutation_counter=mutation_counter,
    )
    return gate, subjects, mutation_counter[0]


def run_verified_probes(*, runner=None, env=None, now=None, urlopen=None,
                        run_suite: bool = True):
    probes = _ORIGINAL_PHASED(
        runner=runner, env=env, now=now, urlopen=urlopen,
        run_suite=run_suite)

    resolved_env = dict(env) if env is not None else go.merged_environment()
    alpaca, account_subjects, final_mutations = _final_account_probe(
        env=resolved_env, urlopen=urlopen)

    gates = dict(probes.gates)
    gates["alpaca_paper_account"] = alpaca
    subjects = dict(probes.subject_values)
    subjects.pop("alpaca_paper_account", None)
    subjects.pop("configured_paper_account", None)
    subjects.update(account_subjects)

    broker_mutations = int(probes.broker_mutation_attempts) + int(final_mutations)
    observed_at = go._utc_text(datetime.now(timezone.utc))
    gates["zero_mutation_boundary"] = go.make_gate(
        "zero_mutation_boundary",
        go.PASS if broker_mutations == 0 and probes.production_db_writes == 0
        else go.FAIL,
        observed_at,
        {"broker_mutation_attempts": broker_mutations,
         "production_db_writes": probes.production_db_writes,
         "allowed_financial_http_methods": ["GET"],
         "final_paper_account_reobserved": True},
    )
    return go.ProbeResults(
        git=probes.git,
        tests=probes.tests,
        gates=gates,
        subject_values=subjects,
        broker_mutation_attempts=broker_mutations,
        production_db_writes=probes.production_db_writes,
        input_mode=probes.input_mode,
        preparation=probes.preparation,
        database_health=probes.database_health,
    )


def _clean_run_pass_path() -> None:
    try:
        go_lock.RUN_PASS_PATH.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise controller.PhaseRefused(
            "prior GO requested-target proof cannot be cleared") from exc


def _current_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(go.ROOT),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    value = (completed.stdout or "").strip()
    if completed.returncode != 0 or go._HEX40.fullmatch(value) is None:
        raise controller.PhaseRefused(
            "current Git identity is unavailable at requested-target proof")
    return value


def _write_run_pass(*, target: str) -> None:
    token = go_lock.current_run_token()
    if token is None:
        raise controller.PhaseRefused(
            "GO requested-target proof has no current lifecycle token")
    boot = phase._boot_id_sha256()
    if boot is None:
        raise controller.PhaseRefused(
            "GO requested-target proof has no current host boot identity")
    evidence = {
        "schema": go_lock.RUN_PASS_SCHEMA,
        "git_commit": _current_head(),
        "requested_target": target,
        "run_token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
        "host_boot_id_sha256": boot,
        "passed_at": go._utc_text(datetime.now(timezone.utc)),
    }
    phase._atomic_write(
        go_lock.RUN_PASS_PATH,
        {**evidence, "evidence_sha256": phase._sha(evidence)},
    )


def _install_wallclock_independent_dual_overlay(*, development: bool) -> None:
    """Add fenced installation authority without changing session verdicts."""
    if development:
        return
    # When executed as a script, make this exact module instance importable by
    # its canonical name before loading the overlays. They must patch the
    # authority path executing under the public lifecycle lock, not a second
    # imported copy of this module.
    sys.modules.setdefault("sentinel_go_verified_entry", sys.modules[__name__])

    # Prepare the database through the newest session that is already causally
    # source-final. A newer closed session remains an explicit readiness/session
    # wait and cannot block installation of the certified software.
    import sentinel_go_24x7_entry as source_final  # noqa: PLC0415
    source_final.install()

    # The installation overlay recognizes only explicitly classified temporal
    # waiting states. SHADOW_GO, DUAL_RUN_GO and PAPER_EXECUTION_GO remain
    # session/economic verdicts and stay NO_GO until current data and pre-open
    # timing are re-earned.
    import sentinel_go_install_entry as install_anytime  # noqa: PLC0415
    install_anytime._install_overlay()


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    development = (
        "--input" in raw or any(str(item).startswith("--input=") for item in raw))
    try:
        phase._strict_target(raw)
        target, _forwarded = controller._target_from_argv(raw)
        if not development:
            if not go_lock.lifecycle_lock_is_held():
                raise controller.PhaseRefused(
                    "production GO entry is available only through the verified locked scripts/sentinel-go-validate.sh lifecycle")
            if go_lock.current_run_token() is None:
                raise controller.PhaseRefused(
                    "production GO entry has no one-run lifecycle capability")
            _clean_run_pass_path()
            try:
                controller.entry.authorize_verified_orchestration()
            except RuntimeError as exc:
                raise controller.PhaseRefused(str(exc)) from exc
        _install_wallclock_independent_dual_overlay(development=development)
        phase.install()
        if not development:
            # Base-backup freshness is a host durability prerequisite. Install
            # its self-heal only after phase.install() has established the exact
            # artifact-certification guard around mutable preparation.
            import sentinel_go_backup_refresh as backup_refresh  # noqa: PLC0415
            backup_refresh.install()
            # Every DB-dependent one-shot phase now shares one cold-start and
            # typed-child-failure contract. This wrapper sits outside the backup
            # refresh so a rebooted/stopped PostgreSQL is recovered before any
            # durability or financial readiness command attempts a connection.
            probe_contract.install(controller=controller, phase=phase)
        # Production GO is intentionally verbose: safe build/test output streams
        # live, sensitive probes emit colored progress/heartbeat lines, suites run
        # shortest-first, and sanitized failing pytest nodes enter the review bundle.
        observability.install(go=go, controller=controller)
        phase.StrictDatabaseHealthView = DeploymentCompatibleDatabaseHealthView
        controller.DatabaseHealthView = DeploymentCompatibleDatabaseHealthView
        controller.run_phased_probes = run_verified_probes
        # Treat the opaque current-run promotion capability as a secret candidate
        # for the existing bundle scanner. Only its SHA-256 is intentionally
        # persisted in the local non-uploaded requested-target proof.
        go._SECRET_NAMES = frozenset(set(go._SECRET_NAMES) | {go_lock.RUN_TOKEN_ENV})
        rc = controller.main(raw)
        if rc == 0 and not development:
            _write_run_pass(target=target)
        return rc
    except controller.PhaseRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
