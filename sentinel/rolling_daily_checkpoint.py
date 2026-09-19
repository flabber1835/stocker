"""Authenticated advancing anchor for the existing immutable shadow records."""
from __future__ import annotations

import hmac
from typing import Literal
from pydantic import Field

from sentinel import rolling_checkpoint as origin, shadow_observation as shadow
from sentinel.feed import publication, operational_snapshot
from sentinel.feed.rolling_contract import Digest, canonical_json, digest

SCHEMA = "sentinel.rolling-daily-checkpoint/1"
CURSOR = "rolling-daily-checkpoint:v1"
INPUT_PREFIX = "rolling-daily-input:v1:"
Refused = origin.RollingColdStartRefused


class Checkpoint(origin.Checkpoint):
    schema_id: Literal["sentinel.rolling-daily-checkpoint/1"] = Field(default=SCHEMA, alias="schema")
    status: Literal["DAILY_CONTINUATION_COMMITTED"] = "DAILY_CONTINUATION_COMMITTED"
    origin_sha256: Digest
    history_anchor: dict


class ReconstructionCheckpoint(Checkpoint):
    schema_id: Literal["sentinel.rolling-reconstruction-checkpoint/1"] = Field(
        default="sentinel.rolling-reconstruction-checkpoint/1", alias="schema")
    status: Literal["RECONSTRUCTION_COMMITTED"] = "RECONSTRUCTION_COMMITTED"


def signature(payload):
    return publication._receipt_hmac({"purpose": payload.get("schema", SCHEMA), "checkpoint": payload})


def input_name(observation_id, session):
    return f"{INPUT_PREFIX}{observation_id}:{session}"


def archive_input(conn, checkpoint):
    result = conn.execute(
        "INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
        " ON CONFLICT DO NOTHING",
        (input_name(checkpoint.observation_id, checkpoint.session), checkpoint.session,
         canonical_json(checkpoint.input_value)))
    if result.rowcount != 1:
        raise Refused("DAILY_INPUT_ARCHIVE_ALREADY_EXISTS")


def require_input(conn, checkpoint):
    row = conn.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s",
                       (input_name(checkpoint.observation_id, checkpoint.session),)).fetchone()
    if row is None or str(row[0]) != checkpoint.session or row[1] != checkpoint.input_value:
        raise Refused("DAILY_INPUT_ARCHIVE_CHANGED")


def read(conn):
    row = conn.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s", (CURSOR,)).fetchone()
    if row is None:
        return None
    raw = row[1]
    if (not isinstance(raw, dict) or set(raw) != {"checkpoint", "hmac_sha256"}
            or not hmac.compare_digest(str(raw["hmac_sha256"]), signature(raw["checkpoint"]))):
        raise Refused("DAILY_CHECKPOINT_AUTHENTICATION_FAILED")
    model = (ReconstructionCheckpoint if raw["checkpoint"].get("schema") ==
             "sentinel.rolling-reconstruction-checkpoint/1" else Checkpoint)
    checkpoint = model.model_validate(raw["checkpoint"])
    if str(row[0]) != checkpoint.session or raw["checkpoint"] != checkpoint.model_dump(by_alias=True):
        raise Refused("DAILY_CHECKPOINT_SHAPE_CHANGED")
    return checkpoint


def write(conn, checkpoint, *, previous):
    payload = checkpoint.model_dump(by_alias=True)
    raw = canonical_json({"checkpoint": payload, "hmac_sha256": signature(payload)})
    if isinstance(previous, Checkpoint):
        result = conn.execute(
            "UPDATE sentinel_processed_sessions SET session=%s,state=%s::jsonb"
            " WHERE cursor_name=%s AND state=%s::jsonb",
            (checkpoint.session, raw, CURSOR, canonical_json({"checkpoint": previous.model_dump(by_alias=True),
                                                           "hmac_sha256": signature(previous.model_dump(by_alias=True))})))
    else:
        result = conn.execute(
            "INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT DO NOTHING", (CURSOR, checkpoint.session, raw))
    if result.rowcount != 1:
        raise Refused("DAILY_CHECKPOINT_CAS_CHANGED")


def _publication(conn, checkpoint):
    row = conn.execute("SELECT version,previous_version,run_id,window_start,window_end,evidence "
                       "FROM sentinel_corpus_publications WHERE version=%s",
                       (checkpoint.publication["version"],)).fetchone()
    if row is None:
        raise Refused("CHECKPOINT_PUBLICATION_MISSING")
    pub = publication.Publication(int(row[0]), row[1], str(row[2]) if row[2] else None,
                                  str(row[3]), str(row[4]), row[5])
    publication._validate_publication(conn, pub, allow_snapshot=True)
    if pub.to_dict() != checkpoint.publication or operational_snapshot._bound(conn, pub) != checkpoint.snapshot:
        raise Refused("CHECKPOINT_PUBLICATION_CHANGED")


def load(conn, context):
    initial = origin.read(conn)
    if initial is None:
        raise Refused("COLD_START_CHECKPOINT_REQUIRED")
    checkpoint = read(conn)
    if checkpoint is None:
        result = origin.restore(conn, initial, **context)
        store = shadow.PostgresShadowObservationStore(conn, observation_id=initial.observation_id, commit_genesis=False)
        observer = shadow.ShadowObserver.resume(
            store=store, observation_id=initial.observation_id, starting_cash=initial.starting_cash,
            first_session=initial.session, controller_config=context["controller"],
            strategy_identity=context["strategy"], runtime_identity=context["runtime"])
        _publication(conn, initial)
        return initial, observer, result
    if (checkpoint.origin_sha256 != digest(initial.model_dump(by_alias=True))
            or checkpoint.genesis_sha256 != initial.genesis_sha256
            or checkpoint.warmup_input_identity != initial.warmup_input_identity
            or checkpoint.observation_id != context["observation_id"]
            or checkpoint.starting_cash != context["starting_cash"]
            or checkpoint.strategy_identity != context["strategy"]
            or checkpoint.runtime_identity != context["runtime"]):
        raise Refused("DAILY_CHECKPOINT_CONFIG_CHANGED")
    store = shadow.PostgresShadowObservationStore(
        conn, observation_id=checkpoint.observation_id, commit_genesis=False, records_from=checkpoint.session)
    from sentinel import rolling_authority
    alien = conn.execute(
        # CASE keeps historical session/input JSON out of lineage inventory.
        # AND predicate order alone cannot guarantee that PostgreSQL skips it.
        "SELECT cursor_name FROM sentinel_processed_sessions WHERE CASE WHEN "
        "cursor_name=ANY(%s) OR cursor_name LIKE %s OR cursor_name LIKE %s OR cursor_name LIKE %s THEN FALSE ELSE "
        "(cursor_name LIKE 'shadow-%%' OR cursor_name LIKE 'rolling-%%' OR cursor_name LIKE 'catchup%%'"
        " OR state ? 'wealth_core' OR state ? 'strategy_identity') END LIMIT 1",
        ([origin.CURSOR, CURSOR, store._genesis_name], store.prefix + "session:%",
         INPUT_PREFIX + checkpoint.observation_id + ":%",
         rolling_authority.prefix(checkpoint.observation_id) + "%")).fetchone()
    if alien:
        raise Refused("DAILY_CHECKPOINT_FOREIGN_LINEAGE")
    require_input(conn, checkpoint)
    observer = shadow.ShadowObserver.resume_checkpoint(
        history_anchor=checkpoint.history_anchor, store=store, observation_id=checkpoint.observation_id,
        starting_cash=checkpoint.starting_cash, first_session=initial.session,
        controller_config=context["controller"], strategy_identity=context["strategy"], runtime_identity=context["runtime"])
    rows, _ = observer._history()
    if (len(rows) != 1 or rows[0]["record_sha256"] != checkpoint.record_sha256
            or rows[0]["state_sha256"] != checkpoint.state_sha256
            or digest(checkpoint.input_value) != rows[0]["input_sha256"]
            or rows[0]["publication"]["publication"] != checkpoint.publication
            or observer.genesis_sha256 != checkpoint.genesis_sha256):
        raise Refused("DAILY_CHECKPOINT_RECORD_CHANGED")
    _publication(conn, checkpoint)
    if isinstance(checkpoint, ReconstructionCheckpoint):
        from sentinel import rolling_reconstruction_evidence as evidence
        evidence.validate_timing(checkpoint.precommit_timing, checkpoint.session)
    else:
        shadow._timing_proof(checkpoint.precommit_timing, decision_session=checkpoint.session,
                             committed=False, where="daily checkpoint precommit timing")
    return checkpoint, observer, observer.verify_history()
