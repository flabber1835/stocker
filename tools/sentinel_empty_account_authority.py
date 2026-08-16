"""Offline Ed25519 issuer for canonical ADMIN_BIND_EMPTY candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

from cryptography.hazmat.primitives import serialization

from sentinel import authority
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
            "empty-account candidate is unreadable") from exc
    try:
        candidate = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IssuanceRefused(
            "empty-account candidate is invalid JSON") from exc
    if (not isinstance(candidate, Mapping)
            or set(candidate) != {"schema", "claims", "retained_evidence"}
            or candidate.get("schema")
            != "sentinel.paper-empty-account-candidate/1"
            or authority.canonical_json_bytes(candidate) != raw):
        raise IssuanceRefused(
            "empty-account candidate is not canonical schema /1")
    claims = candidate["claims"]
    evidence = candidate["retained_evidence"]
    try:
        authority.validate_empty_account_certificate_claims(claims)
    except authority.AuthorityRefused as exc:
        raise IssuanceRefused(str(exc)) from exc
    if (not isinstance(evidence, Mapping)
            or evidence.get("schema")
            != "sentinel.paper-empty-account-evidence/1"
            or claims["retained_evidence"]["sha256"]
            != authority.canonical_sha256(evidence)):
        raise IssuanceRefused(
            "empty-account retained evidence differs from signed claims")
    for field in (
            "authorization_mode", "historical_causality",
            "historical_certification", "scope", "subject",
            "durable_rollout", "bindings"):
        if claims.get(field) != evidence.get(field):
            raise IssuanceRefused(
                f"empty-account evidence {field} differs from signed claims")
    review = evidence.get("review")
    if (not isinstance(review, Mapping)
            or set(review) != {"reviewer", "ticket", "reviewed_at",
                               "authority_effect"}
            or not review.get("reviewer") or not review.get("ticket")
            or review.get("authority_effect") != authority.ADMIN_BIND_EMPTY):
        raise IssuanceRefused(
            "empty-account candidate lacks an exact attended review record")
    return claims, evidence


def issue(*, candidate: Path, private_key_file: Path, key_id: str,
          output: Path) -> str:
    claims, _evidence = _candidate(candidate)
    key = _load_private_key(private_key_file)
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    actual_key_id = authority.key_id_for_public_key(public)
    if key_id != actual_key_id:
        raise IssuanceRefused(
            f"issuer key id mismatch: private key is {actual_key_id}")
    unsigned = authority.unsigned_envelope_bytes(
        key_id=key_id, claims=claims)
    payload = authority.signed_envelope_bytes(
        key_id=key_id, claims=claims, signature=key.sign(unsigned))
    _atomic_no_clobber(output, payload)
    return hashlib.sha256(payload).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline Ed25519 ADMIN_BIND_EMPTY issuer")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("issue")
    command.add_argument("--candidate", type=Path, required=True)
    command.add_argument("--private-key-file", type=Path, required=True)
    command.add_argument("--key-id", required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument(
        "--confirm-issue-admin-bind-empty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_issue_admin_bind_empty:
        print(
            "REFUSED: --confirm-issue-admin-bind-empty is required",
            file=sys.stderr)
        return 2
    try:
        digest = issue(
            candidate=args.candidate,
            private_key_file=args.private_key_file,
            key_id=args.key_id, output=args.output)
    except (authority.AuthorityRefused, IssuanceRefused,
            OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "issued": True,
        "authorization_mode": authority.ADMIN_BIND_EMPTY,
        "historical_causality": (
            authority.HISTORICAL_CAUSALITY_UNVERIFIED),
        "certificate_sha256": digest,
        "output": str(args.output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
