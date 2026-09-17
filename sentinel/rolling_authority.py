"""Authenticated, append-only authority for the bounded rolling shadow scope."""
from __future__ import annotations

import hmac
from typing import Literal

from pydantic import Field

from sentinel.feed import publication
from sentinel.feed.rolling_contract import Contract, Digest, canonical_json, digest
from sentinel import shadow_observation as shadow

SCHEMA = "sentinel.rolling-shadow-runtime/1"
SCOPE = "ROLLING_CHECKPOINT_AND_CURRENT_INPUTS"
PREFIX = "shadow-rolling-runtime:v1:"


class Refused(shadow.ShadowObservationRefused):
    pass


class Authority(Contract):
    schema_id: Literal["sentinel.rolling-shadow-runtime/1"] = Field(default=SCHEMA, alias="schema")
    scope: Literal["ROLLING_CHECKPOINT_AND_CURRENT_INPUTS"] = SCOPE
    observation_id: str
    session: str
    checkpoint_sha256: Digest
    record_sha256: Digest
    state_sha256: Digest
    input_sha256: Digest
    runtime_sha256: Digest
    publication_sha256: Digest
    previous_authority_sha256: Digest | None
    previous_record_sha256: Digest | None
    readiness_sha256: Digest
    timing: dict
    pitr: dict


def prefix(observation_id):
    return PREFIX + shadow._observation_id(observation_id) + ":"


def name(observation_id, session):
    return prefix(observation_id) + session


def signature(payload):
    return publication._receipt_hmac({"purpose": SCHEMA, "authority": payload})


def latest(conn, observation_id):
    rows = conn.execute(
        "SELECT cursor_name,session,state FROM sentinel_processed_sessions "
        "WHERE cursor_name LIKE %s ORDER BY session DESC LIMIT 2",
        (prefix(observation_id) + "%",)).fetchall()
    values = []
    for cursor, session, raw in rows:
        if not isinstance(raw, dict) or set(raw) != {"authority", "hmac_sha256"}:
            raise Refused("ROLLING_AUTHORITY_SHAPE_CHANGED")
        payload = raw["authority"]
        if not hmac.compare_digest(str(raw["hmac_sha256"]), signature(payload)):
            raise Refused("ROLLING_AUTHORITY_AUTHENTICATION_FAILED")
        value = Authority.model_validate(payload)
        if (value.model_dump(by_alias=True) != payload or value.observation_id != observation_id
                or str(session) != value.session or cursor != name(observation_id, value.session)):
            raise Refused("ROLLING_AUTHORITY_IDENTITY_CHANGED")
        shadow._timing_proof(value.timing, decision_session=value.session, committed=True,
                             where="rolling runtime post-commit timing")
        values.append(value)
    return values


def require_binding(authority, checkpoint):
    if (authority.checkpoint_sha256 != digest(checkpoint.model_dump(by_alias=True))
            or authority.record_sha256 != checkpoint.record_sha256
            or authority.state_sha256 != checkpoint.state_sha256
            or authority.input_sha256 != digest(checkpoint.input_value)
            or authority.publication_sha256 != digest(checkpoint.publication)
            or authority.runtime_sha256 != digest(checkpoint.runtime_identity)
            or authority.observation_id != checkpoint.observation_id
            or authority.session != checkpoint.session):
        raise Refused("ROLLING_AUTHORITY_CHECKPOINT_CHANGED")


def append(conn, value):
    payload = value.model_dump(by_alias=True)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
                 (name(value.observation_id, value.session), value.session,
                  canonical_json({"authority": payload, "hmac_sha256": signature(payload)})))
