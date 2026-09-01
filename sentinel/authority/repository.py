"""Exact PostgreSQL persistence for signed authority and rollout state.

This module never commits or rolls back.  Lifecycle owners define transaction
boundaries and call these operations in the established lock order.
"""
from __future__ import annotations

import json
from typing import Mapping

from .canonical import _parse_manifest, _sha256
from .model import (
    AuthorityRefused,
    RolloutMode,
    RolloutState,
    SystemCertificate,
)


def authority_state_for_install(
        conn) -> tuple[int, int, str | None, bool]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT generation,highest_issuer_generation,"
            " active_certificate_sha256 FROM sentinel_execution_authority_state"
            " WHERE id=1 FOR UPDATE")
        row = cur.fetchone()
        if row is not None:
            return (int(row[0]), int(row[1]),
                    str(row[2]) if row[2] else None, True)
        cur.execute("SELECT COUNT(*) FROM sentinel_signed_execution_certificates")
        if int(cur.fetchone()[0]) != 0:
            raise AuthorityRefused(
                "durable signed-authority singleton is missing; refusing repair")
        # Do not create durable state until all certificate/supersession checks
        # have passed.  That keeps a refused install side-effect free even for
        # direct callers that catch the refusal and later commit their outer
        # transaction.
        return 0, 0, None, False


def key_is_revoked(conn, key_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_execution_key_revocations WHERE key_id=%s",
            (key_id,))
        return cur.fetchone() is not None


def maximum_installed_issuer_generation(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(issuer_generation),0)"
            " FROM sentinel_signed_execution_certificates")
        return int(cur.fetchone()[0])


def exact_envelope_bytes(conn, certificate_sha256: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT envelope_bytes FROM sentinel_signed_execution_certificates"
            " WHERE certificate_sha256=%s", (certificate_sha256,))
        return cur.fetchone()


def insert_staged_certificate(
        conn, *, actual: str, certificate_bytes: bytes, certificate,
        claims: Mapping, generation: int, authority_state_exists: bool,
        reason: str, not_before, expires_at):
    with conn.cursor() as cur:
        if not authority_state_exists:
            cur.execute(
                "INSERT INTO sentinel_execution_authority_state"
                " (id,generation,highest_issuer_generation) VALUES (1,0,0)"
                " ON CONFLICT (id) DO NOTHING")
            if cur.rowcount != 1:
                raise AuthorityRefused(
                    "signed authority state changed concurrently")
        cur.execute(
            "INSERT INTO sentinel_signed_execution_certificates"
            " (certificate_sha256,certificate_id,key_id,envelope_bytes,envelope,"
            " claims,issuer_generation,supersedes_certificate_sha256,"
            " not_before,expires_at)"
            " VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s)"
            " RETURNING install_sequence,installed_at",
            (actual, claims["certificate_id"], certificate.key_id,
             certificate_bytes, json.dumps(certificate.envelope, sort_keys=True),
             json.dumps(claims, sort_keys=True), claims["issuer_generation"],
             claims["supersedes_certificate_sha256"], not_before, expires_at))
        install_sequence, installed_at = cur.fetchone()
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_lifecycle"
            " (certificate_sha256,status) VALUES (%s,'STAGED')", (actual,))
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,'STAGED',%s)", (generation, actual, reason))
    return install_sequence, installed_at


def load_signed_row(conn, certificate_sha256: str):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT c.envelope_bytes,c.envelope,c.claims,c.key_id,"
            " c.certificate_id,c.issuer_generation,"
            " c.supersedes_certificate_sha256,c.not_before,c.expires_at,"
            " c.install_sequence,c.installed_at,l.status,"
            " a.generation,a.highest_issuer_generation,"
            " a.active_certificate_sha256"
            " FROM sentinel_signed_execution_certificates c"
            " JOIN sentinel_execution_certificate_lifecycle l"
            "   USING (certificate_sha256)"
            " LEFT JOIN sentinel_execution_authority_state a ON a.id=1"
            " WHERE c.certificate_sha256=%s", (certificate_sha256,))
        return cur.fetchone()


def durable_revocation_flags(
        conn, *, certificate_sha256: str, key_id: str) -> tuple[bool, bool]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_execution_certificate_revocations"
            " WHERE certificate_sha256=%s", (certificate_sha256,))
        certificate_revoked = cur.fetchone() is not None
        cur.execute(
            "SELECT 1 FROM sentinel_execution_key_revocations WHERE key_id=%s",
            (key_id,))
        key_revoked = cur.fetchone() is not None
    return certificate_revoked, key_revoked


def newest_installed_generation(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(issuer_generation)"
            " FROM sentinel_signed_execution_certificates")
        return int(cur.fetchone()[0])


def activate_certificate_rows(
        conn, *, certificate_sha256: str, claims: Mapping,
        current: RolloutState, generation: int, active_sha: str | None,
        next_mode: RolloutMode, next_version: int,
        next_rollout_sha: str | None, next_generation: int, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_rollout_state SET mode=%s,version=%s,"
            " certificate_sha256=%s,updated_at=NOW()"
            " WHERE id=1 AND version=%s AND mode=%s"
            " AND certificate_sha256 IS NOT DISTINCT FROM %s",
            (next_mode.value, next_version, next_rollout_sha,
             current.version, current.mode.value, current.certificate_sha256))
        if cur.rowcount != 1:
            raise AuthorityRefused(
                "rollout changed concurrently during certificate activation")
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (%s,%s,%s,%s,%s)",
            (next_version, current.mode.value, next_mode.value,
             next_rollout_sha, reason))
        if active_sha is not None:
            cur.execute(
                "SELECT status FROM sentinel_execution_certificate_lifecycle"
                " WHERE certificate_sha256=%s FOR UPDATE", (active_sha,))
            predecessor = cur.fetchone()
            if predecessor is None or predecessor[0] not in {"ACTIVE", "REVOKED"}:
                raise AuthorityRefused("active authority predecessor is invalid")
            predecessor_was_active = predecessor[0] == "ACTIVE"
            cur.execute(
                "UPDATE sentinel_execution_certificate_lifecycle"
                " SET status='RETIRED',retired_at=NOW()"
                " WHERE certificate_sha256=%s AND status='ACTIVE'",
                (active_sha,))
            if predecessor_was_active:
                cur.execute(
                    "INSERT INTO sentinel_execution_certificate_events"
                    " (authority_generation,certificate_sha256,action,detail)"
                    " VALUES (%s,%s,'RETIRED',%s)",
                    (next_generation, active_sha, reason))
        cur.execute(
            "UPDATE sentinel_execution_certificate_lifecycle"
            " SET status='ACTIVE',activated_at=NOW()"
            " WHERE certificate_sha256=%s AND status='STAGED'",
            (certificate_sha256,))
        if cur.rowcount != 1:
            raise AuthorityRefused("staged certificate changed concurrently")
        cur.execute(
            "UPDATE sentinel_execution_authority_state"
            " SET generation=%s,highest_issuer_generation=%s,"
            " active_certificate_sha256=%s,updated_at=NOW()"
            " WHERE id=1 AND generation=%s"
            " AND active_certificate_sha256 IS NOT DISTINCT FROM %s",
            (next_generation, claims["issuer_generation"], certificate_sha256,
             generation, active_sha))
        if cur.rowcount != 1:
            raise AuthorityRefused("authority state changed concurrently")
        action = "ROTATED" if active_sha is not None else "ACTIVATED"
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,%s,%s)",
            (next_generation, certificate_sha256, action, reason))


def load_active_authority_rows(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT generation,highest_issuer_generation,"
            " active_certificate_sha256 FROM sentinel_execution_authority_state"
            " WHERE id=1")
        return cur.fetchall()


def revoke_certificate_rows(
        conn, *, certificate_sha256: str, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM sentinel_execution_certificate_lifecycle"
            " WHERE certificate_sha256=%s FOR UPDATE", (certificate_sha256,))
        row = cur.fetchone()
        if row is None or row[0] == "REVOKED":
            raise AuthorityRefused("the confirmed signed certificate is not revocable")
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_revocations"
            " (certificate_sha256,reason) VALUES (%s,%s)",
            (certificate_sha256, reason))
        cur.execute(
            "UPDATE sentinel_execution_certificate_lifecycle"
            " SET status='REVOKED',revoked_at=NOW(),revocation_reason=%s"
            " WHERE certificate_sha256=%s", (reason, certificate_sha256))
        cur.execute(
            "SELECT generation,active_certificate_sha256"
            " FROM sentinel_execution_authority_state WHERE id=1 FOR UPDATE")
        state = cur.fetchone()
        generation = int(state[0]) if state else 0
        if state and state[1] == certificate_sha256:
            generation += 1
            cur.execute(
                "UPDATE sentinel_execution_authority_state"
                " SET generation=%s,updated_at=NOW() WHERE id=1",
                (generation,))
        cur.execute(
            "INSERT INTO sentinel_execution_certificate_events"
            " (authority_generation,certificate_sha256,action,detail)"
            " VALUES (%s,%s,'REVOKED',%s)",
            (generation, certificate_sha256, reason))


def revoke_key_rows(conn, *, key_id: str, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_signed_execution_certificates"
            " WHERE key_id=%s", (key_id,))
        execution_count = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_signed_administrative_certificates"
            " WHERE key_id=%s", (key_id,))
        administrative_count = int(cur.fetchone()[0])
        if execution_count + administrative_count == 0:
            raise AuthorityRefused("the confirmed key_id has no installed certificate")
        cur.execute(
            "INSERT INTO sentinel_execution_key_revocations (key_id,reason)"
            " VALUES (%s,%s) ON CONFLICT (key_id) DO NOTHING", (key_id, reason))
        if cur.rowcount != 1:
            raise AuthorityRefused("the confirmed key is already revoked")
        cur.execute(
            "SELECT generation,active_certificate_sha256"
            " FROM sentinel_execution_authority_state WHERE id=1 FOR UPDATE")
        state = cur.fetchone()
        if execution_count:
            generation = int(state[0]) + 1 if state else 0
            active_sha = str(state[1]) if state and state[1] else "0" * 64
            if state:
                cur.execute(
                    "UPDATE sentinel_execution_authority_state"
                    " SET generation=%s,updated_at=NOW() WHERE id=1",
                    (generation,))
            cur.execute(
                "INSERT INTO sentinel_execution_certificate_events"
                " (authority_generation,certificate_sha256,action,detail)"
                " VALUES (%s,%s,'KEY_REVOKED',%s)",
                (generation, active_sha, f"{key_id}: {reason}"))
        cur.execute(
            "SELECT generation,active_certificate_sha256"
            " FROM sentinel_administrative_authority_state"
            " WHERE id=1 FOR UPDATE")
        administrative_state = cur.fetchone()
        if administrative_state:
            administrative_generation = int(administrative_state[0]) + 1
            administrative_sha = (
                str(administrative_state[1])
                if administrative_state[1] else "0" * 64)
            cur.execute(
                "UPDATE sentinel_administrative_authority_state"
                " SET generation=%s,updated_at=NOW() WHERE id=1",
                (administrative_generation,))
            cur.execute(
                "INSERT INTO sentinel_administrative_certificate_events"
                " (authority_generation,certificate_sha256,action,detail)"
                " VALUES (%s,%s,'KEY_REVOKED',%s)",
                (administrative_generation, administrative_sha,
                 f"{key_id}: {reason}"))


def _row_to_certificate(row) -> SystemCertificate:
    certificate_sha, raw, stored, raw_modes, installed_at = row
    payload = bytes(raw)
    actual = _sha256(payload)
    if actual != str(certificate_sha):
        raise AuthorityRefused(
            "durable system-certificate bytes do not match their SHA-256")
    parsed = _parse_manifest(payload)
    stored_mapping = (stored if isinstance(stored, Mapping)
                      else json.loads(stored))
    if parsed != stored_mapping:
        raise AuthorityRefused(
            "durable system-certificate parsed record differs from its bytes")
    modes_value = (raw_modes if isinstance(raw_modes, list)
                   else json.loads(raw_modes))
    try:
        modes = tuple(RolloutMode(str(value)) for value in modes_value)
    except ValueError as exc:
        raise AuthorityRefused(
            "durable system certificate contains an unknown rollout mode") from exc
    return SystemCertificate(
        str(certificate_sha), parsed, modes, installed_at=installed_at)


def load_active_certificate(conn) -> SystemCertificate | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT certificate_sha256,manifest_bytes,manifest,"
            " allowed_rollout_modes,installed_at"
            " FROM sentinel_system_certificates WHERE revoked_at IS NULL")
        rows = cur.fetchall()
    if not rows:
        return None
    if len(rows) != 1:  # The partial unique index should make this impossible.
        raise AuthorityRefused("more than one system certificate is active")
    return _row_to_certificate(rows[0])


def signed_certificate_exists(conn, certificate_sha256: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM sentinel_signed_execution_certificates"
            " WHERE certificate_sha256=%s", (certificate_sha256,))
        return cur.fetchone() is not None


def revoke_legacy_certificate_rows(
        conn, *, certificate_sha256: str, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_system_certificates"
            " SET revoked_at=NOW(),revocation_reason=%s"
            " WHERE certificate_sha256=%s AND revoked_at IS NULL",
            (reason, certificate_sha256))
        if cur.rowcount != 1:
            raise AuthorityRefused(
                "the confirmed certificate is not the active certificate")
        cur.execute(
            "INSERT INTO sentinel_system_certificate_events"
            " (certificate_sha256,action,detail) VALUES (%s,'REVOKED',%s)",
            (certificate_sha256, reason))


def load_rollout_state(conn) -> RolloutState:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT mode,version,certificate_sha256"
            " FROM sentinel_rollout_state WHERE id=1")
        row = cur.fetchone()
    if row is None:
        raise AuthorityRefused("durable rollout state is missing")
    try:
        mode = RolloutMode(str(row[0]))
    except ValueError as exc:
        raise AuthorityRefused(
            f"durable rollout mode {row[0]!r} is unknown") from exc
    version = int(row[1])
    if version < 1:
        raise AuthorityRefused("durable rollout version is invalid")
    certificate_sha = str(row[2]) if row[2] else None
    if mode is RolloutMode.PINNED_1_00 and certificate_sha is not None:
        raise AuthorityRefused(
            "pinned rollout state unexpectedly carries controller authority")
    if mode is RolloutMode.CONTROLLER and certificate_sha is None:
        raise AuthorityRefused(
            "controller rollout state has no authorizing certificate")
    return RolloutState(mode, version, certificate_sha)


def set_rollout_rows(
        conn, *, current: RolloutState, next_state: RolloutState,
        reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_rollout_state SET mode=%s,version=%s,"
            " certificate_sha256=%s,updated_at=NOW()"
            " WHERE id=1 AND version=%s",
            (next_state.mode.value, next_state.version,
             next_state.certificate_sha256, current.version))
        if cur.rowcount != 1:
            raise AuthorityRefused(
                "rollout state changed concurrently; inspect before retrying")
        cur.execute(
            "INSERT INTO sentinel_rollout_events"
            " (version,from_mode,to_mode,certificate_sha256,reason)"
            " VALUES (%s,%s,%s,%s,%s)",
            (next_state.version, current.mode.value, next_state.mode.value,
             next_state.certificate_sha256, reason))
