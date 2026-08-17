"""Current facts bound by renewable PAPER_OBSERVATION_ONLY leases."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from sentinel.authority import (
    AuthorityRefused,
    DEFAULT_OBSERVATION_CERTIFICATE_LIFETIME,
    HISTORICAL_CAUSALITY_UNVERIFIED,
    MAX_OBSERVATION_CERTIFICATE_LIFETIME,
    PAPER_BASE_URL,
    PAPER_OBSERVATION_ONLY,
    PAPER_SCOPE,
    RolloutMode,
    bind_current_immutable_identities,
    canonical_json_bytes,
    canonical_sha256,
    execution_config_identity,
    runtime_artifact_identity,
    validate_observation_certificate_claims,
)
from sentinel.feed.publication import require_current, visible_predicate


ACCEPTED_BOUNDARY_PATH = (
    Path(__file__).resolve().parents[1]
    / "config" / "paper-observation-boundary.json")


def accepted_boundary_bytes(
        path: Path = ACCEPTED_BOUNDARY_PATH) -> bytes:
    try:
        payload = Path(path).read_bytes().rstrip(b"\r\n")
    except OSError as exc:
        raise AuthorityRefused(
            "paper-observation accepted-boundary record is unreadable") from exc
    # Reuse the certificate parser's canonical type rules without treating this
    # reviewed record as authority. Its digest is later carried by signed claims.
    import json
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityRefused(
            "paper-observation accepted-boundary record is invalid JSON") from exc
    if canonical_json_bytes(value) != payload:
        raise AuthorityRefused(
            "paper-observation accepted-boundary record is not canonical")
    expected = {
        "schema": "sentinel.paper-observation-accepted-boundary/1",
        "authorization_mode": "PAPER_OBSERVATION_ONLY",
        "historical_causality": "HISTORICAL_CAUSALITY_UNVERIFIED",
        "historical_certification": "NOT_GRANTED",
        "scope": "ALPACA_PAPER",
    }
    if any(value.get(field) != expected_value
           for field, expected_value in expected.items()):
        raise AuthorityRefused(
            "paper-observation accepted boundary was weakened or relabelled")
    experiment = value.get("cold_start_experiment")
    result = experiment.get("result") if isinstance(experiment, Mapping) else None
    if (not isinstance(experiment, Mapping)
            or experiment.get("decision_session") != "2026-07-31"
            or experiment.get("measured_sessions") != 253
            or experiment.get("variants") != [
                "CURRENT_ISSUER_METADATA", "IDENTITY_ONLY_METADATA",
                "METADATA_MINIMAL"]
            or not isinstance(result, Mapping)
            or result.get("positions") != 25
            or result.get("target_membership_identical") is not True
            or result.get("target_weights_identical") is not True):
        raise AuthorityRefused(
            "paper-observation accepted cold-start boundary differs")
    return payload


def accepted_boundary_sha256(
        path: Path = ACCEPTED_BOUNDARY_PATH) -> str:
    return hashlib.sha256(accepted_boundary_bytes(path)).hexdigest()


def current_metadata_snapshot_identity(conn) -> Mapping:
    """Hash the newest complete visible TICKERS content deterministically.

    The observation date is retained separately. The content digest excludes
    it, so a later complete delivery of byte-for-byte-equivalent metadata does
    not require needless certificate rotation. A content or membership change
    does.
    """
    visibility = visible_predicate("u")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(snapshot_date) FROM sentinel_universe u"
            f" WHERE {visibility}")
        row = cur.fetchone()
        snapshot = row[0] if row else None
        if snapshot is None:
            raise AuthorityRefused(
                "current visible TICKERS metadata snapshot is missing")
        cur.execute(
            "SELECT permaticker,ticker,category,sector,related_tickers,"
            " first_price_date,last_price_date,is_delisted"
            " FROM sentinel_universe u WHERE snapshot_date=%s"
            f" AND {visibility}"
            " ORDER BY permaticker,ticker",
            (snapshot,))
        rows = cur.fetchall()
    if not rows:
        raise AuthorityRefused(
            "current visible TICKERS metadata snapshot is empty")
    content = [{
        "permaticker": str(permaticker),
        "ticker": str(ticker),
        "category": category,
        "sector": sector,
        "related_tickers": related,
        "first_price_date": (first.isoformat() if first else None),
        "last_price_date": (last.isoformat() if last else None),
        "is_delisted": bool(delisted),
    } for (permaticker, ticker, category, sector, related, first, last,
           delisted) in rows]
    return {
        "snapshot_date": snapshot.isoformat(),
        "row_count": len(content),
        "sha256": canonical_sha256(content),
    }


def current_corpus_root_identity(conn) -> Mapping:
    """Bind the current publication as the root of the permitted lineage."""
    from sentinel.execution.authority_gate import publication_row_sha256

    current = require_current(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version,previous_version,run_id,published_at,window_start,"
            " window_end,evidence FROM sentinel_corpus_publications"
            " WHERE version=%s", (current.version,))
        row = cur.fetchone()
    if row is None:
        raise AuthorityRefused(
            "current publication row disappeared while binding authority")
    return {
        "data_version": current.version,
        "publication_chain_root_sha256": publication_row_sha256(row),
    }


def metadata_matches_claim(claimed: Mapping, current: Mapping) -> bool:
    """Permit only equal content on the same or a later observation date."""
    return bool(
        current.get("snapshot_date") >= claimed.get("snapshot_date")
        and current.get("row_count") == claimed.get("row_count")
        and current.get("sha256") == claimed.get("sha256"))


def current_warmup_evidence(conn, *, starting_cash: float) -> Mapping:
    """Run the mandatory current 252+1 cold start without broker access."""
    from sentinel.core.bootstrap import bootstrap

    visibility = visible_predicate("b")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session FROM (SELECT DISTINCT session FROM sentinel_bars b"
            f" WHERE {visibility} ORDER BY session DESC LIMIT 253) s"
            " ORDER BY session")
        sessions = [str(row[0]) for row in cur.fetchall()]
    if len(sessions) != 253:
        raise AuthorityRefused(
            "paper-observation candidate requires exactly 253 current "
            f"sessions, found {len(sessions)}")
    book = bootstrap(
        conn, start=sessions[0], end=sessions[-1],
        starting_cash=float(starting_cash))
    record = {
        "schema": "sentinel.paper-observation-warmup/1",
        "historical_causality": HISTORICAL_CAUSALITY_UNVERIFIED,
        "historical_certification": "NOT_GRANTED",
        "measured_sessions": 253,
        "warmup_sessions": book.warmup_sessions,
        "first_session": sessions[0],
        "decision_session": sessions[-1],
        "target_book": _evidence_value(book.to_dict()),
    }
    if book.warmup_sessions != 252 or book.session != sessions[-1]:
        raise AuthorityRefused(
            "paper-observation warmup did not produce a 252+1 cold start")
    return record


def _evidence_value(value):
    """Make computed evidence canonical without signing binary floats."""
    if isinstance(value, float):
        if not value == value or value in {float("inf"), float("-inf")}:
            raise AuthorityRefused(
                "paper-observation warmup contains a non-finite number")
        return format(Decimal(str(value)), "f")
    if isinstance(value, Mapping):
        return {str(key): _evidence_value(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_evidence_value(item) for item in value]
    return value


def _utc_second(value: datetime, *, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AuthorityRefused(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _instant_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_candidate(
        conn, *, certificate_id: str, issuer_generation: int,
        deployment_id: str, expected_account: str,
        runtime_identity: Mapping, strategy_identity: Mapping,
        automation_config_sha256: str, warmup: Mapping,
        maximum_exposure: str, reviewer: str, ticket: str,
        not_before: datetime, expires_at: datetime | None = None,
        now: datetime | None = None) -> Mapping:
    """Build reviewed unsigned evidence/claims from current durable facts."""
    from sentinel import binding as binding_mod
    from sentinel.authority import load_rollout_state
    from sentinel.controller.frozen_rule import load as load_controller
    from sentinel.execution.authority_gate import (
        PUBLICATION_POLICY_SCHEMA,
        publication_policy_implementation_sha256,
    )

    now = _utc_second(now or datetime.now(timezone.utc), label="issued_at")
    not_before = _utc_second(not_before, label="not_before")
    expires_at = _utc_second(
        expires_at or not_before + DEFAULT_OBSERVATION_CERTIFICATE_LIFETIME,
        label="expires_at")
    if not_before < now:
        raise AuthorityRefused(
            "paper-observation not_before "
            f"{_instant_text(not_before)} precedes lifecycle reference "
            f"{_instant_text(now)}")
    if expires_at - not_before > MAX_OBSERVATION_CERTIFICATE_LIFETIME:
        raise AuthorityRefused(
            "paper-observation candidate lifetime exceeds 35 days")
    if not reviewer.strip() or not ticket.strip():
        raise AuthorityRefused(
            "paper-observation candidate requires reviewer and ticket")

    bound = binding_mod.require(conn)
    if (bound.deployment_id != deployment_id
            or bound.broker_account_id != expected_account
            or bound.broker != "alpaca"):
        raise AuthorityRefused(
            "paper-observation candidate account/deployment differs from "
            "durable binding")
    rollout = load_rollout_state(conn)
    if rollout.mode not in {RolloutMode.PINNED_1_00, RolloutMode.CONTROLLER}:
        raise AuthorityRefused("paper-observation rollout source is unknown")

    artifacts = runtime_artifact_identity(runtime_identity)
    environment = runtime_identity.get("environment") or {}
    sentinel_source = environment.get("sentinel_source") or {}
    wealth_source = environment.get("wealth_core_source") or {}
    image_lock = environment.get("image_lock_sha256")
    corpus = current_corpus_root_identity(conn)
    metadata = current_metadata_snapshot_identity(conn)
    controller = load_controller()
    policy_implementation = publication_policy_implementation_sha256()
    bindings = {
        "git_commit": artifacts["git_commit"],
        "runtime_image_digest": artifacts["runtime_image_digest"],
        "test_image_digest": artifacts["test_image_digest"],
        "sentinel_source_sha256": sentinel_source.get("hash"),
        "wealth_core_source_sha256": wealth_source.get("hash"),
        "requirements_lock_sha256": image_lock,
        "runtime_identity_sha256": runtime_identity.get("identity_hash"),
        "strategy_identity_sha256": canonical_sha256(strategy_identity),
        "execution_config_sha256": canonical_sha256(
            execution_config_identity(paper_base_url=PAPER_BASE_URL)),
        "automation_config_sha256": automation_config_sha256,
        "current_corpus": corpus,
        "current_metadata_snapshot": metadata,
        "publication_policy": {
            "schema": PUBLICATION_POLICY_SCHEMA,
            "implementation_sha256": policy_implementation,
            "chain_root_sha256": corpus[
                "publication_chain_root_sha256"],
        },
        "controller": {
            "rule_sha256": controller.digest,
            "config_sha256": canonical_sha256(controller.to_dict()),
        },
    }
    bindings = bind_current_immutable_identities(
        bindings, runtime_identity=runtime_identity,
        strategy_identity=strategy_identity, paper_base_url=PAPER_BASE_URL,
        automation_config_sha256=automation_config_sha256,
        current_corpus=corpus, current_metadata_snapshot=metadata)
    subject = {
        "deployment_id": bound.deployment_id,
        "broker": bound.broker,
        "broker_account_id": bound.broker_account_id,
        "takeover_epoch": bound.takeover_epoch,
        "environment": PAPER_SCOPE,
        "paper_base_url": PAPER_BASE_URL,
    }
    rollout_claim = {
        "from_mode": rollout.mode.value,
        "from_version": rollout.version,
        "from_certificate_sha256": rollout.certificate_sha256,
        "to_mode": RolloutMode.CONTROLLER.value,
        "to_version": rollout.version + 1,
    }
    boundary_sha = accepted_boundary_sha256()
    warmup_sha = canonical_sha256(warmup)
    evidence = {
        "schema": "sentinel.paper-observation-evidence/1",
        "authorization_mode": PAPER_OBSERVATION_ONLY,
        "historical_causality": HISTORICAL_CAUSALITY_UNVERIFIED,
        "historical_certification": "NOT_GRANTED",
        "scope": PAPER_SCOPE,
        "accepted_boundary_sha256": boundary_sha,
        "warmup": dict(warmup),
        "subject": subject,
        "rollout": rollout_claim,
        "bindings": bindings,
        "maximum_exposure": str(maximum_exposure),
        "review": {
            "reviewer": reviewer.strip(),
            "ticket": ticket.strip(),
            "reviewed_at": _instant_text(now),
            "authority_effect": "PAPER_OBSERVATION_ONLY",
        },
    }
    evidence_sha = canonical_sha256(evidence)
    claims = {
        "certificate_id": certificate_id,
        "issuer_generation": issuer_generation,
        "issued_at": _instant_text(now),
        "not_before": _instant_text(not_before),
        "expires_at": _instant_text(expires_at),
        "authorization_mode": PAPER_OBSERVATION_ONLY,
        "historical_causality": HISTORICAL_CAUSALITY_UNVERIFIED,
        "historical_certification": "NOT_GRANTED",
        "scope": PAPER_SCOPE,
        "unattended_automation": True,
        "allowed_rollout_modes": [RolloutMode.CONTROLLER.value],
        "permitted_operations": sorted({
            "AUTOMATION", "CANCEL", "EXECUTE_READ", "PREPARE_READ",
            "SAFETY_CANCEL", "SAFETY_READ", "SUBMIT"}),
        "subject": subject,
        "rollout": rollout_claim,
        "bindings": bindings,
        "maximum_exposure": str(maximum_exposure),
        "retained_evidence": {
            "schema": "sentinel.paper-observation-evidence/1",
            "sha256": evidence_sha,
            "accepted_boundary_sha256": boundary_sha,
            "warmup_sha256": warmup_sha,
        },
        "supersedes_certificate_sha256": rollout.certificate_sha256,
    }
    validate_observation_certificate_claims(claims)
    return {
        "schema": "sentinel.paper-observation-candidate/1",
        "claims": claims,
        "retained_evidence": evidence,
    }


__all__ = [
    "ACCEPTED_BOUNDARY_PATH", "accepted_boundary_bytes",
    "accepted_boundary_sha256", "current_corpus_root_identity",
    "current_metadata_snapshot_identity", "current_warmup_evidence",
    "build_candidate", "metadata_matches_claim",
]
