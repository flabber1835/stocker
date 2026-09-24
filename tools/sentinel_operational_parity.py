"""Read-only current-strategy startup and serialize/restart equivalence proof.

This uses the production warm-up and kernel on the published operational
window. Historical return certification remains in its dedicated runners.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from sentinel import identity
from sentinel.core.decision import publication_fingerprint
from sentinel.core.kernel import advance_session
from sentinel.core.production import load_published_session
from sentinel.core.session import SessionState
from sentinel.feed import publication, store, rolling_go_inputs
from sentinel.feed.readiness import REQUIRED_SPY_SESSIONS
from sentinel.shadow_observation import FullyPublishedSession
from sentinel.shadow_runtime import WARMUP_SESSIONS, _fresh_seed, _starting_cash
from sentinel.strategy import production_strategy

REPORT_SCHEMA = "sentinel.production-operational-parity/1"
PROOF_SCOPE = "CURRENT_STRATEGY_STARTUP_AND_RESTART"
CHECKS = (
    "prior_unchanged", "input_unchanged", "restart_equivalent",
    "result_roundtrip_equivalent", "frontier_advanced",
    "publication_version_bound", "strategy_bound", "decision_present",
)


class OperationalParityRefused(RuntimeError):
    """The operational proof could not establish its evidence boundary."""


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        default=str).encode("utf-8")).hexdigest()


def _begin_snapshot(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        cur.execute("SHOW transaction_isolation")
        isolation = str(cur.fetchone()[0]).lower()
        cur.execute("SHOW transaction_read_only")
        read_only = str(cur.fetchone()[0]).lower()
    if isolation != "repeatable read" or read_only != "on":
        raise OperationalParityRefused("read-only repeatable-read snapshot required")
    return {"isolation": isolation, "read_only": read_only}


def prove_transition(prior, published, *, held, controller, strategy) -> dict:
    """Exercise the actual kernel with native and restored production state."""
    wrapped = FullyPublishedSession(published, publication=held.to_dict())
    wrapped.commitment()
    input_hash = wrapped.input_sha256
    prior_hash = prior.state_hash
    restored = SessionState.from_dict(json.loads(json.dumps(prior.to_dict())))
    result = advance_session(
        prior, published, controller_config=controller, strategy_identity=strategy)
    restarted = advance_session(
        restored, published, controller_config=controller, strategy_identity=strategy)
    roundtrip = SessionState.from_dict(json.loads(json.dumps(result.to_dict())))
    checks = {
        "prior_unchanged": prior.state_hash == restored.state_hash == prior_hash,
        "input_unchanged": wrapped.input_sha256 == input_hash,
        "restart_equivalent": result.to_dict() == restarted.to_dict(),
        "result_roundtrip_equivalent": result.to_dict() == roundtrip.to_dict(),
        "frontier_advanced": result.last_processed_session == published.session,
        "publication_version_bound": result.data_version == held.version,
        "strategy_bound": result.strategy_identity == strategy,
        "decision_present": isinstance(result.last_decision, dict)
                            and bool(result.last_decision),
    }
    if not all(checks.values()):
        raise OperationalParityRefused(
            "transition checks failed: " + ", ".join(
                key for key in CHECKS if not checks[key]))
    return {
        "input_sha256": input_hash,
        "prior_state_sha256": prior_hash,
        "result_state_sha256": result.state_hash,
        "decision_sha256": _hash(result.last_decision),
        "checks": checks,
    }


def run_proof(conn, *, starting_cash: str, expected_commit: str) -> dict:
    try:
        revision = os.environ.get("SENTINEL_IMAGE_SOURCE_REVISION")
        if revision != expected_commit:
            raise OperationalParityRefused("image source revision differs from GO")
        source = identity.rehearsal_identity()
        environment = source["environment"]
        if not (environment.get("compatible") is True
                and environment.get("lock_present") is True):
            raise OperationalParityRefused("image computational environment uncertified")
        cash = _starting_cash(starting_cash)
        controller, strategy = production_strategy()
        rolling_go_inputs.require_schemas(conn)
        transaction = _begin_snapshot(conn)
        with rolling_go_inputs.pinned(conn) as held:
            rolling = rolling_go_inputs.is_rolling(held)
            frontier = held.window_end if rolling else store.latest_visible_session(conn)
            if not frontier or held.window_end != frontier:
                raise OperationalParityRefused("publication does not end at visible frontier")
            formation_proof = None
            if rolling:
                from sentinel.rolling_runtime import SCHEMA as runtime_contract
                from sentinel.controller.machine import Controller
                from sentinel.core.production import warm_session_state
                from sentinel.rolling_initialization import _published
                from sentinel.shadow_runtime import _warmup_input_identity
                rolling_go_inputs.require_first_deployment(conn)
                from sentinel.controller.owned_impairment import enabled as owned
                if owned(strategy):
                    # Readiness uses counts; formation owns its one feature
                    # window. Do not retain a second, unused warmup corpus.
                    binding, _ = rolling_go_inputs.validate_status(conn, held)
                    from sentinel.core.formation_inputs import FormationInputs
                    from sentinel.core import formation_preview
                    source_inputs = FormationInputs(conn, binding, held)
                    prior, warmup, published, formation_proof = formation_preview.run(
                        source_inputs, capital=cash, strategy=strategy, data_version=held.version)
                else:
                    binding, material, _ = rolling_go_inputs.validate(conn, held)
                    prior = warm_session_state(
                        SessionState.fresh(starting_cash=float(cash), controller=Controller(controller),
                                           strategy_identity=strategy), material.warmup,
                        publication_version=held.version, prospective_concordance_witness=True)
                    warmup = _warmup_input_identity(material.warmup, material.warmup.sessions,
                                                   prospective_witness=True)
                    published = _published(material, held)
                coherence = {"coherent": True, "scope": rolling_go_inputs.SCOPE,
                             "version": held.version, "blocking_runs": [], "snapshot": binding}
            else:
                coherence = publication.assert_operationally_coherent(
                    conn, frontier=frontier).to_dict()
                prior, warmup = _fresh_seed(
                    conn, first_session=frontier, starting_cash=cash,
                    controller_config=controller, strategy_identity=strategy,
                    publication_version=held.version)
                published = load_published_session(
                    conn, frontier, spy_sessions=REQUIRED_SPY_SESSIONS)
            if warmup.get("session_count") != WARMUP_SESSIONS:
                raise OperationalParityRefused("incomplete production feature warm-up")
            transition = prove_transition(
                prior, published, held=held, controller=controller, strategy=strategy)
            held_identity = {
                "publication_fingerprint": publication_fingerprint(held),
                "visible_frontier": frontier,
            }
            current = rolling_go_inputs.current(conn) if rolling else publication.current(conn)
            visible = current.window_end if rolling else store.latest_visible_session(conn)
            if (publication_fingerprint(current)
                    != held_identity["publication_fingerprint"]
                    or visible != frontier):
                raise OperationalParityRefused("publication changed during proof")
        return {
            "schema": REPORT_SCHEMA,
            "verdict": "PASS",
            "authority_effect": "NONE",
            "runtime_authority_changed": False,
            "transaction": transaction,
            "publication_coherence": coherence,
            "held_publication": held_identity,
            "source_identity": {
                "identity_hash": source["identity_hash"],
                "environment": environment,
                "image_source_revision": revision,
            },
            "proof": {
                **({"runtime_contract": runtime_contract} if rolling else {}),
                "scope": ("ROLLING_FORMED_STARTUP_AND_RESTART" if formation_proof else
                          "ROLLING_STARTUP_AND_RESTART" if rolling else PROOF_SCOPE),
                **({'formation': formation_proof} if formation_proof else {}),
                "strategy_identity": strategy,
                "controller_configuration_sha256": controller.digest,
                "starting_cash": format(cash.normalize(), "f"),
                "decision_session": frontier,
                "data_version": held.version,
                "warmup_input": warmup,
                "sentinel_source_sha256": environment["sentinel_source"]["hash"],
                "wealth_core_source_sha256": environment["wealth_core_source"]["hash"],
                "proof_helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                **transition,
            },
        }
    finally:
        conn.rollback()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starting-cash", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    conn = None
    try:
        conn = store.connect(os.environ["SENTINEL_DATABASE_URL"])
        report = run_proof(
            conn, starting_cash=args.starting_cash, expected_commit=args.expected_commit)
    except Exception as exc:
        report = {"schema": REPORT_SCHEMA, "verdict": "REFUSED",
                  "error_type": type(exc).__name__}
        if isinstance(exc, OperationalParityRefused):
            report["reason"] = str(exc)
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps(report, sort_keys=True, allow_nan=False, default=str))
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
