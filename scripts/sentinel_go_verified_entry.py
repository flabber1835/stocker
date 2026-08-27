#!/usr/bin/env python3
"""Supported phased GO entry with fresh final volatile-account evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import sys
from typing import Optional, Sequence

import sentinel_go_phase_entry as phase

controller = phase.controller
go = controller.go
_ORIGINAL_PHASED = controller.run_phased_probes


class DeploymentCompatibleDatabaseHealthView(phase.StrictDatabaseHealthView):
    """Enforce fresh margin without silently changing the public bundle schema.

    The autonomous deployment parser intentionally requires the exact v1
    database-health field set. Fresh wall-clock margin is enforced by
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    try:
        phase._strict_target(raw)
        phase.install()
        phase.StrictDatabaseHealthView = DeploymentCompatibleDatabaseHealthView
        controller.DatabaseHealthView = DeploymentCompatibleDatabaseHealthView
        controller.run_phased_probes = run_verified_probes
        return controller.main(raw)
    except controller.PhaseRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
