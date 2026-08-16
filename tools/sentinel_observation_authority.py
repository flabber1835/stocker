"""Offline issuer for canonical PAPER_OBSERVATION_ONLY candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

from cryptography.hazmat.primitives import serialization

from sentinel.authority import (
    AuthorityRefused,
    canonical_json_bytes,
    canonical_sha256,
    key_id_for_public_key,
    signed_envelope_bytes,
    unsigned_envelope_bytes,
    validate_observation_certificate_claims,
)
from sentinel.observation_authority import accepted_boundary_sha256
from tools.sentinel_certificate_issuer import (
    IssuanceRefused,
    _atomic_no_clobber,
    _load_private_key,
)


def _candidate(path: Path) -> tuple[Mapping, Mapping]:
    try:
        raw = Path(path).read_bytes().rstrip(b"\r\n")
    except OSError as exc:
        raise IssuanceRefused(
            "paper-observation candidate is unreadable") from exc
    try:
        candidate = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IssuanceRefused(
            "paper-observation candidate is invalid JSON") from exc
    if (not isinstance(candidate, Mapping)
            or set(candidate) != {"schema", "claims", "retained_evidence"}
            or candidate.get("schema")
            != "sentinel.paper-observation-candidate/1"
            or canonical_json_bytes(candidate) != raw):
        raise IssuanceRefused(
            "paper-observation candidate is not canonical schema /1")
    claims = candidate["claims"]
    evidence = candidate["retained_evidence"]
    try:
        validate_observation_certificate_claims(claims)
    except AuthorityRefused as exc:
        raise IssuanceRefused(str(exc)) from exc
    if (not isinstance(evidence, Mapping)
            or evidence.get("schema")
            != "sentinel.paper-observation-evidence/1"):
        raise IssuanceRefused("retained paper-observation evidence is invalid")
    retained = claims["retained_evidence"]
    if (retained["sha256"] != canonical_sha256(evidence)
            or retained["accepted_boundary_sha256"]
            != accepted_boundary_sha256()
            or retained["accepted_boundary_sha256"]
            != evidence.get("accepted_boundary_sha256")
            or retained["warmup_sha256"]
            != canonical_sha256(evidence.get("warmup"))):
        raise IssuanceRefused(
            "signed retained-evidence identities differ from candidate bytes")
    for field in ("authorization_mode", "historical_causality",
                  "historical_certification", "scope", "subject", "rollout",
                  "bindings", "maximum_exposure"):
        if claims.get(field) != evidence.get(field):
            raise IssuanceRefused(
                f"candidate evidence {field} differs from signed claims")
    review = evidence.get("review")
    if (not isinstance(review, Mapping)
            or set(review) != {"reviewer", "ticket", "reviewed_at",
                               "authority_effect"}
            or not review.get("reviewer") or not review.get("ticket")
            or review.get("authority_effect") != "PAPER_OBSERVATION_ONLY"):
        raise IssuanceRefused(
            "paper-observation candidate lacks an exact review record")
    warmup = evidence.get("warmup")
    if (not isinstance(warmup, Mapping)
            or warmup.get("schema") != "sentinel.paper-observation-warmup/1"
            or warmup.get("historical_causality")
            != "HISTORICAL_CAUSALITY_UNVERIFIED"
            or warmup.get("historical_certification") != "NOT_GRANTED"
            or warmup.get("measured_sessions") != 253
            or warmup.get("warmup_sessions") != 252):
        raise IssuanceRefused(
            "paper-observation candidate lacks the current 252+1 warmup")
    return claims, evidence


def issue(*, candidate: Path, private_key_file: Path, key_id: str,
          output: Path) -> str:
    claims, _evidence = _candidate(candidate)
    key = _load_private_key(private_key_file)
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    actual_key_id = key_id_for_public_key(public)
    if key_id != actual_key_id:
        raise IssuanceRefused(
            f"issuer key id mismatch: private key is {actual_key_id}")
    unsigned = unsigned_envelope_bytes(key_id=key_id, claims=claims)
    payload = signed_envelope_bytes(
        key_id=key_id, claims=claims, signature=key.sign(unsigned))
    _atomic_no_clobber(output, payload)
    return hashlib.sha256(payload).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline Ed25519 PAPER_OBSERVATION_ONLY issuer")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("issue")
    command.add_argument("--candidate", type=Path, required=True)
    command.add_argument("--private-key-file", type=Path, required=True)
    command.add_argument("--key-id", required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument(
        "--confirm-issue-paper-observation-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_issue_paper_observation_only:
        print(
            "REFUSED: --confirm-issue-paper-observation-only is required",
            file=sys.stderr)
        return 2
    try:
        digest = issue(
            candidate=args.candidate,
            private_key_file=args.private_key_file,
            key_id=args.key_id, output=args.output)
    except (AuthorityRefused, IssuanceRefused, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "issued": True,
        "authorization_mode": "PAPER_OBSERVATION_ONLY",
        "historical_causality": "HISTORICAL_CAUSALITY_UNVERIFIED",
        "certificate_sha256": digest,
        "output": str(args.output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
