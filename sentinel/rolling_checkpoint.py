"""Authenticated first-state closure; never a GO or execution certificate."""
from __future__ import annotations

import hmac
from typing import Literal

from pydantic import Field, model_validator

from sentinel.feed import publication
from sentinel.feed.rolling_contract import Contract, Digest, canonical_json, digest
from sentinel import shadow_observation as shadow

SCHEMA = "sentinel.rolling-cold-start/1"
CURSOR = "rolling-cold-start:v1"


class RollingColdStartRefused(RuntimeError):
    pass


class Checkpoint(Contract):
    schema_id: Literal["sentinel.rolling-cold-start/1"] = Field(default=SCHEMA, alias="schema")
    status: Literal["COLD_START_COMMITTED", "FORMED_START_COMMITTED"] = "COLD_START_COMMITTED"
    observation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,63}$")
    session: str
    starting_cash: str
    strategy_identity: dict
    runtime_identity: dict
    snapshot: dict
    publication: dict
    genesis_sha256: Digest
    record_sha256: Digest
    state_sha256: Digest
    input_value: dict
    warmup_input_identity: dict
    precommit_timing: dict
    pitr: dict

    @model_validator(mode='after')
    def origin_kind(self):
        # Daily/reconstruction checkpoints inherit fields but refer to their
        # current publication. Their retained origin is authenticated separately.
        if self.schema_id != SCHEMA:
            return self
        from sentinel import formed_origin
        formed = self.warmup_input_identity.get('schema') == formed_origin.SCHEMA
        if formed != (self.status == 'FORMED_START_COMMITTED'):
            raise ValueError('checkpoint origin kind differs from initialization evidence')
        if formed and (self.warmup_input_identity['snapshot_id'] != self.snapshot['snapshot_id']
                       or self.warmup_input_identity['publication_sha256'] != digest(self.publication)):
            raise ValueError('formed origin publication binding differs')
        return self


def _signature(payload):
    return publication._receipt_hmac({"purpose": SCHEMA, "checkpoint": payload})


def read(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s", (CURSOR,))
        row = cur.fetchone()
    if row is None:
        return None
    raw = row[1]
    if not isinstance(raw, dict) or set(raw) != {"checkpoint", "hmac_sha256"}:
        raise RollingColdStartRefused("CHECKPOINT_SHAPE_CHANGED")
    payload = raw["checkpoint"]
    if not hmac.compare_digest(str(raw["hmac_sha256"]), _signature(payload)):
        raise RollingColdStartRefused("CHECKPOINT_AUTHENTICATION_FAILED")
    checkpoint = Checkpoint.model_validate(payload)
    if payload != checkpoint.model_dump(by_alias=True) or str(row[0]) != checkpoint.session:
        raise RollingColdStartRefused("CHECKPOINT_SESSION_CHANGED")
    return checkpoint


def write(conn, checkpoint: Checkpoint):
    payload = checkpoint.model_dump(by_alias=True)
    value = {"checkpoint": payload, "hmac_sha256": _signature(payload)}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sentinel_processed_sessions (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
                    (CURSOR, checkpoint.session, canonical_json(value)))


def lineage_names(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT cursor_name FROM sentinel_processed_sessions WHERE "
                    "cursor_name LIKE 'shadow-%%' OR cursor_name LIKE 'rolling-%%' "
                    "OR cursor_name LIKE 'catchup%%' OR state ? 'wealth_core' OR state ? 'strategy_identity'")
        return {str(row[0]) for row in cur.fetchall()}


def require_fresh(conn):
    if lineage_names(conn):
        raise RollingColdStartRefused("EXISTING_STRATEGY_STATE_REQUIRES_ADMISSION")
    for table, reason in (
            ("sentinel_execution_plans", "EXISTING_EXECUTION_HISTORY_REQUIRES_ADMISSION"),
            ("sentinel_commands", "EXISTING_EXECUTION_HISTORY_REQUIRES_ADMISSION"),
            ("sentinel_fills", "EXISTING_EXECUTION_HISTORY_REQUIRES_ADMISSION"),
            ("sentinel_trial_strategy_evidence", "EXISTING_STRATEGY_EVIDENCE_REQUIRES_ADMISSION")):
        with conn.cursor() as cur:
            cur.execute("SELECT EXISTS (SELECT 1 FROM " + table + ")")
            if cur.fetchone()[0]:
                raise RollingColdStartRefused(reason)


def restore(conn, checkpoint, *, observation_id, starting_cash, controller, strategy, runtime):
    return restore_observer(
        conn, checkpoint, observation_id=observation_id, starting_cash=starting_cash,
        controller=controller, strategy=strategy, runtime=runtime)[1]


def restore_observer(conn, checkpoint, *, observation_id, starting_cash, controller, strategy, runtime,
                     status_only=False):
    """Verify exactly one committed origin, without reading old price payloads."""
    if (checkpoint.observation_id != observation_id or checkpoint.starting_cash != starting_cash
            or checkpoint.strategy_identity != strategy or checkpoint.runtime_identity != runtime):
        raise RollingColdStartRefused("CHECKPOINT_CONFIG_CHANGED")
    store = shadow.PostgresShadowObservationStore(conn, observation_id=observation_id, commit_genesis=False,
                                                 stream_state=status_only)
    from sentinel import rolling_authority
    names = lineage_names(conn)
    names.discard(rolling_authority.name(observation_id, checkpoint.session))
    if names != {CURSOR, store._genesis_name, store._name(checkpoint.session)}:
        raise RollingColdStartRefused("CHECKPOINT_LINEAGE_CHANGED")
    observer = shadow.ShadowObserver.resume(
        store=store, observation_id=observation_id, starting_cash=starting_cash,
        first_session=checkpoint.session, controller_config=controller,
        strategy_identity=strategy, runtime_identity=runtime, status_only=status_only)
    rows, state = observer._history(consume_seed=True) if status_only else observer._history()
    if (observer.genesis_sha256 != checkpoint.genesis_sha256
            or len(rows) != 1 or rows[0].get("record_sha256") != checkpoint.record_sha256
            or digest(checkpoint.input_value) != rows[0].get("input_sha256")
            or observer.warmup_input_identity != checkpoint.warmup_input_identity):
        raise RollingColdStartRefused("CHECKPOINT_RECORD_BINDING_CHANGED")
    if rows[0]["publication"]["publication"] != checkpoint.publication:
        raise RollingColdStartRefused("CHECKPOINT_PUBLICATION_CHANGED")
    result = observer._result(
        session=rows[0]["session"], state=state,
        strategy_economics=rows[0]["strategy_economics"],
        record_sha256=rows[0]["record_sha256"], appended=False)
    del rows
    if result.state.state_hash != checkpoint.state_sha256:
        raise RollingColdStartRefused("CHECKPOINT_STATE_CHANGED")
    with conn.cursor() as cur:
        cur.execute("SELECT version,previous_version,run_id,window_start,window_end,evidence "
                    "FROM sentinel_corpus_publications WHERE version=%s", (result.state.data_version,))
        row = cur.fetchone()
    if row is None:
        raise RollingColdStartRefused("CHECKPOINT_PUBLICATION_MISSING")
    pub = publication.Publication(int(row[0]), row[1], str(row[2]) if row[2] else None,
                                  str(row[3]), str(row[4]), row[5])
    publication._validate_publication(conn, pub, allow_snapshot=True)
    if pub.to_dict() != checkpoint.publication:
        raise RollingColdStartRefused("CHECKPOINT_PUBLICATION_CHANGED")
    shadow._timing_proof(checkpoint.precommit_timing, decision_session=checkpoint.session,
                         committed=False, where="rolling checkpoint precommit timing")
    return None if status_only else observer, result
