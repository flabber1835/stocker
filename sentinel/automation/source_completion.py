"""Small producer-change hints; never source verification or authority."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class RowVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relation: StrictInt = Field(gt=0, le=4294967295)
    xmin: str = Field(pattern=r"^[0-9]{1,20}$")
    ctid: str = Field(pattern=r"^\([0-9]{1,20},[0-9]{1,10}\)$")


class SourceCompletionHint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["sentinel.source-completion-hint/1"] = "sentinel.source-completion-hint/1"
    observation_id: str = Field(pattern=r"^[A-Za-z0-9.-]{1,64}$")
    decision_session: date
    publication_version: StrictInt = Field(gt=0, le=9223372036854775807)
    publication_frontier: date
    publication_row: RowVersion
    attestation_row: RowVersion | None = None

    @model_validator(mode="after")
    def _prospective_scope(self):
        if self.publication_frontier > self.decision_session:
            raise ValueError("source hint belongs to a later decision")
        return self


def read(conn, *, observation_id: str, decision_session: date) -> SourceCompletionHint | None:
    """Read one statement snapshot without detoasting source or book JSON.

    The caller owns this read-only connection. An absent target attestation is
    represented explicitly so its later insertion can wake the second handoff.
    Exact key/session matching prevents another observation from supplying it.
    """
    from sentinel.rolling_authority import name

    target = date.fromisoformat(str(decision_session))
    cursor = name(observation_id, target.isoformat())
    row = conn.execute(
        "SELECT p.version,p.window_end,p.tableoid::oid,p.xmin::text,p.ctid::text,"
        " a.session,a.tableoid::oid,a.xmin::text,a.ctid::text "
        "FROM (SELECT version,window_end,tableoid,xmin,ctid "
        " FROM sentinel_corpus_publications ORDER BY version DESC LIMIT 1) p "
        "LEFT JOIN sentinel_processed_sessions a ON a.cursor_name=%s",
        (cursor,),
    ).fetchone()
    if row is None:
        return None
    if row[5] is not None and row[5] != target:
        return None
    return SourceCompletionHint(
        observation_id=observation_id, decision_session=target,
        publication_version=row[0], publication_frontier=row[1],
        publication_row=RowVersion(relation=row[2], xmin=row[3], ctid=row[4]),
        attestation_row=(RowVersion(relation=row[6], xmin=row[7], ctid=row[8])
                         if row[5] is not None else None),
    )


def progressed(previous, current, *, decision_session: date) -> bool:
    """Only a same-subject producer advance may shorten a source backoff."""
    try:
        before = SourceCompletionHint.model_validate(previous)
        after = SourceCompletionHint.model_validate(current)
    except (ValueError, TypeError):
        return False
    if (before.observation_id != after.observation_id
            or before.decision_session != decision_session
            or after.decision_session != decision_session
            or after.publication_frontier != decision_session):
        return False
    if after.publication_version > before.publication_version:
        return after.publication_frontier >= before.publication_frontier
    return bool(
        after.publication_version == before.publication_version
        and after.publication_frontier == before.publication_frontier
        and after.publication_row == before.publication_row
        and after.attestation_row is not None
        and after.attestation_row != before.attestation_row
    )
