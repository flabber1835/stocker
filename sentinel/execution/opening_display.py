"""One GET-only broker observation for the current PAPER opening display."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinel import local_paper
from sentinel.execution import journal
from sentinel.execution.alpaca import AlpacaCredentialsRefused, UnmappedBrokerStatus
from sentinel.execution.contract import MalformedBrokerEvidence
from sentinel.execution.states import IN_FLIGHT, CommandState


FLAG = 'operator_opening_observation'
SCHEMA = 'sentinel.operator-opening-observation/1'
START_LEAD = timedelta(minutes=3)
FRESHNESS = timedelta(minutes=10)
TIMEOUT_SECONDS = 18
_ACTIVE = sorted(state.value for state in IN_FLIGHT | {CommandState.PLANNED})


class Scope(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')

    cycle_id: str = Field(min_length=1, max_length=256)
    plan_id: str = Field(min_length=1, max_length=256)
    plan_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    generation: int = Field(strict=True, gt=0)
    fence: int = Field(strict=True, gt=0)
    reconciliation: int = Field(strict=True, gt=0)
    execute_at: datetime


class Receipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')

    schema_version: Literal[SCHEMA]
    scope: Scope
    observed_at: datetime

    def current_at(self, now: datetime) -> bool:
        if (self.observed_at.utcoffset() != timedelta(0)
                or self.scope.execute_at.utcoffset() != timedelta(0)):
            return False
        first = self.scope.execute_at - START_LEAD
        return first <= self.observed_at < self.scope.execute_at and self.observed_at <= now < self.observed_at + FRESHNESS


def _scope(conn, bound, *, collecting):
    states = ('WAITING_OPEN',) if collecting else ('WAITING_OPEN', 'EXECUTING')
    row = conn.execute("""
        SELECT x.cycle_id,x.plan_id,x.plan_fingerprint,
               c.generation,l.fence_token,o.seq,x.execute_at,clock_timestamp()
        FROM sentinel_automation_control c
        JOIN sentinel_automation_lease l ON l.id=1 AND l.control_generation=c.generation
        JOIN sentinel_automation_cycles x ON x.control_generation=c.generation
          AND (x.deployment_id,x.broker,x.broker_account_id,x.takeover_epoch)=
              (c.deployment_id,c.broker,c.broker_account_id,c.takeover_epoch)
        JOIN sentinel_execution_plans p ON p.plan_id=x.plan_id
          AND (p.deployment_id,p.broker,p.broker_account_id,p.takeover_epoch)=
              (x.deployment_id,x.broker,x.broker_account_id,x.takeover_epoch)
        JOIN LATERAL (SELECT seq,completeness,runtime_state,orders
                       FROM sentinel_observations ORDER BY seq DESC LIMIT 1) o
          ON o.seq::text=x.last_clean_reconciliation_id
        WHERE c.id=1 AND c.enabled AND NOT c.kill_switch_engaged AND c.authority_verdict='PASS'
          AND (c.deployment_id,c.broker,c.broker_account_id,c.takeover_epoch)=(%s,%s,%s,%s)
          AND l.holder_id IS NOT NULL AND l.expires_at>clock_timestamp()
          AND x.last_fence_token=l.fence_token AND x.certificate_sha256=c.certificate_sha256
          AND x.config_sha256=c.config_sha256 AND x.rollout_version=c.rollout_version
          AND x.rollout_mode=c.rollout_mode AND x.state=ANY(%s)
          AND NOT x.historical_state_only AND x.plan_fingerprint IS NOT NULL
          AND x.failure_code IS NULL AND x.failure_detail IS NULL
          AND x.execute_at=x.execution_open_at+interval '1 minute'
          AND c.enabled_at < x.execution_open_at
          AND p.superseded_by IS NULL AND p.data_version::text=x.data_version
          AND p.publication_fingerprint=x.publication_fingerprint
          AND p.effective_session=x.effective_session AND p.decision_session=x.decision_session
          AND p.rollout_mode=c.rollout_mode AND p.rollout_version=c.rollout_version
          AND p.rollout_certificate_sha256=c.certificate_sha256
          AND o.completeness='COMPLETE' AND o.runtime_state='RUNNING'
          AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(o.orders) AS item
                          WHERE item->>'state' IS NULL OR item->>'state' NOT IN
                            ('FILLED','CANCELLED','REJECTED','SUPERSEDED','EXPIRED'))
          AND NOT EXISTS (SELECT 1 FROM sentinel_commands WHERE state=ANY(%s))
          AND clock_timestamp()>=x.execute_at-%s
          AND clock_timestamp()<x.execute_at+%s
        LIMIT 2
    """, (*bound, list(states), _ACTIVE, START_LEAD, timedelta(0) if collecting else FRESHNESS)).fetchall()
    if len(row) != 1:
        return None
    cycle, plan, fingerprint, generation, fence, reconciliation, execute, now = row[0]
    return Scope(cycle_id=cycle, plan_id=plan, plan_fingerprint=fingerprint,
                 generation=generation, fence=fence, reconciliation=reconciliation,
                 execute_at=execute.astimezone(timezone.utc)), now


def _saved(conn, bound, scope, now):
    rows = conn.execute("""
        SELECT flags->%s FROM (
            SELECT flags FROM sentinel_broker_account_evidence
            WHERE broker=%s AND broker_account_id=%s AND observed_at<=%s
              AND observed_at>%s
            ORDER BY observed_at DESC,seq DESC LIMIT 24
        ) recent WHERE flags ? %s
    """, (FLAG, bound[1], bound[2], now, now-FRESHNESS, FLAG)).fetchall()
    for raw, in rows:
        try:
            receipt = Receipt.model_validate(raw)
        except ValueError:
            continue
        if receipt.scope == scope and receipt.current_at(now):
            return receipt
    return None


def _positions(pairs: Iterable[tuple[str | None, Decimal]]) -> dict[str, Decimal] | None:
    positions = {}
    for asset, qty in pairs:
        if not asset or asset in positions or not qty.is_finite() or qty < 0:
            return None
        positions[asset] = qty
    return positions


async def collect(conn, *, reader, bound):
    """Read fresh, stable positions/orders and compare with the clean journal anchor."""
    sample = _scope(conn, bound, collecting=True)
    if sample is None:
        return None
    scope, now = sample
    if _saved(conn, bound, scope, now) is not None:
        return None
    try:
        payload = journal.load_observation_payload(conn, scope.reconciliation)
    except journal.ObservationEvidenceUncertifiable:
        return None
    if (payload['broker'], payload['account_id']) != bound[1:3] or payload['completeness'] != 'COMPLETE':
        return None
    expected = _positions((row['broker_id'], Decimal(row['quantity'])) for row in payload['positions'])
    if expected is None:
        return None
    conn.commit()
    # The canonical observer double-reads orders and positions, with account
    # identity checks around each phase. This collector grants no write port.
    import httpx
    try:
        observation = await asyncio.wait_for(reader.observe(), TIMEOUT_SECONDS)
    except (TimeoutError, httpx.HTTPError, MalformedBrokerEvidence,
            AlpacaCredentialsRefused, UnmappedBrokerStatus):
        return None
    account = observation.account_identity
    if (not observation.is_complete or observation.orders or account is None
            or (account.broker, account.account_id) != bound[1:3]):
        return None
    actual = _positions((p.instrument.broker_id, p.quantity) for p in observation.positions)
    if actual != expected:
        return None
    return Receipt(schema_version=SCHEMA, scope=scope, observed_at=observation.observed_at)


def confirm(conn, bound, receipt):
    """Recheck ownership, the exact cycle and journal after native collection."""
    sample = _scope(conn, bound, collecting=True)
    if sample is not None and sample[0] == receipt.scope and receipt.current_at(sample[1]):
        return receipt.model_dump(mode='json')
    return None


def observed_at(conn, *, cycle_id, plan_id, reconciliation=None, waiting=False):
    """Use only a fresh matching display observation while its clean anchor survives."""
    owner = local_paper.bound_account(conn)
    if owner is None:
        return None
    bound = (owner.deployment_id, owner.broker, owner.broker_account_id, owner.takeover_epoch)
    current = _scope(conn, bound, collecting=waiting)
    if current is None:
        return None
    scope, now = current
    if ((scope.cycle_id, scope.plan_id) != (cycle_id, plan_id)
            or reconciliation is not None and scope.reconciliation != reconciliation):
        return None
    receipt = _saved(conn, bound, scope, now)
    return receipt.observed_at if receipt is not None else None
