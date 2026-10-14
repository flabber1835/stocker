"""Explicit initial anchor repair for an unchanged, never-traded paper DB."""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel import binding, empty_account
from sentinel.automation import store as automation_store
from sentinel.execution import alpaca, journal
from sentinel.execution.guarded import PaperPreparationGrant, GuardedExecutionBroker
from sentinel.feed import publication
from sentinel.feed.rolling_contract import canonical_json, digest
from sentinel.paper.model import PaperActivationRefused as Refused

SCHEMA = 'sentinel.initial-paper-incarnation-recovery/1'
CURSOR = 'initial-paper-incarnation-recovery:v1'


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    system_identifier: str = Field(pattern=r'^[1-9][0-9]{5,25}$')
    actor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    same_host_confirmed: bool
    retain_current_paper_credentials: bool

    @field_validator('same_host_confirmed', 'retain_current_paper_credentials')
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError('initial paper recovery requires explicit confirmations')
        return value

    @field_validator('actor', 'reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('operator identity and reason cannot be blank')
        return value


def _signature(value):
    return publication._receipt_hmac({'purpose': SCHEMA, 'receipt': value})


def _local(conn, request, *, final=False):
    bound = binding.require(conn)
    prior, current, _ = alpaca.database_incarnation(conn, initialize=False)
    control = automation_store.load_control(conn, for_update=final)
    lease = conn.execute('SELECT EXISTS(SELECT 1 FROM sentinel_automation_lease WHERE holder_id IS NOT NULL AND expires_at>clock_timestamp())').fetchone()[0]
    counts = conn.execute('SELECT (SELECT COUNT(*) FROM sentinel_commands),(SELECT COUNT(*) FROM sentinel_fills)').fetchone()
    recovering = conn.execute('SELECT pg_is_in_recovery()').fetchone()[0]
    checks = dict(paper_binding=bound.broker == 'alpaca', initial_epoch=bound.takeover_epoch == 1,
                  original_cluster=current['system_identifier'] == request.system_identifier,
                  original_timeline=current['timeline_id'] == 1, not_restoring=recovering is False,
                  killed=not control.enabled and control.kill_switch_engaged, no_live_lease=lease is False,
                  never_traded=counts == (0, 0))
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise Refused('initial paper recovery refused: ' + ', '.join(failed))
    return bound, prior, current


def _fresh_empty(account, observation, expected):
    empty_account._complete_flat(observation, label='initial paper recovery')
    empty_account._strict_account(account, expected_account=expected, observation=observation)
    if account.cash != account.equity:
        raise Refused('initial paper recovery flat account cash differs from equity')
    age = (datetime.now(timezone.utc) - observation.observed_at).total_seconds()
    if not -5 <= age <= 30:
        raise Refused('initial paper recovery observation is not fresh')


async def authorize(conn, *, broker, grant, request, fresh_authority):
    request = Request.model_validate(request)
    if not isinstance(grant, PaperPreparationGrant):
        raise Refused('initial paper recovery is attended preparation only')
    if not isinstance(broker, GuardedExecutionBroker) or broker.grant != grant:
        raise Refused('initial paper recovery requires the matching guarded read broker')
    from sentinel.paper.inspection import _require_certified_paper_broker
    _require_certified_paper_broker(broker)
    with journal.writer_lock(conn):
        bound, prior, current = _local(conn, request)
        if grant.expected_account != bound.broker_account_id:
            raise Refused('initial paper recovery account differs from its read grant')
        certificate = fresh_authority()
        if not isinstance(certificate, str) or re.fullmatch('[0-9a-f]{64}', certificate) is None:
            raise Refused('initial paper recovery signed certificate identity is malformed')
        row = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (CURSOR,)).fetchone()
        if row is not None:
            raw = row[0]
            if (not isinstance(raw, dict) or set(raw) != {'receipt', 'hmac_sha256'}
                    or not hmac.compare_digest(str(raw['hmac_sha256']), _signature(raw['receipt']))):
                raise Refused('initial paper recovery receipt authentication failed')
            value = raw['receipt']
            if (not isinstance(value, dict) or set(value) != {'schema', 'request', 'binding', 'incarnation',
                    'certificate_sha256', 'authority_effect', 'credential_policy', 'broker_mutations',
                    'observed_at', 'observations', 'account_facts_sha256'}
                    or value.get('schema') != SCHEMA or value.get('request') != request.model_dump()
                    or value.get('binding') != bound.to_dict() or value.get('incarnation') != current
                    or value.get('authority_effect') != 'NONE' or prior != current
                    or value.get('credential_policy') != 'RETAINED_CURRENT_PAPER'
                    or value.get('broker_mutations') != 0):
                raise Refused('initial paper recovery receipt scope differs')
            return dict(value, resumed=True)
        if prior is not None or not alpaca.upgrade_restore_reason(conn):
            raise Refused('initial paper recovery requires the unanchored legacy backup fence')

        first_account = await broker.account_snapshot()
        first = await broker.observe()
        _fresh_empty(first_account, first, bound.broker_account_id)
        second_account = await broker.account_snapshot()
        second = await broker.observe()
        _fresh_empty(second_account, second, bound.broker_account_id)
        if (empty_account._account_facts(first_account) != empty_account._account_facts(second_account)
                or second.observed_at < first.observed_at):
            raise Refused('initial paper recovery account observations are not stable')
        after, anchor, actual = _local(conn, request, final=True)
        if after != bound or anchor is not None or actual != current or fresh_authority() != certificate:
            raise Refused('initial paper recovery lost its current identity or authority')
        value = dict(schema=SCHEMA, request=request.model_dump(), binding=bound.to_dict(),
                     incarnation=current, certificate_sha256=certificate, authority_effect='NONE',
                     credential_policy='RETAINED_CURRENT_PAPER', broker_mutations=0,
                     observed_at=datetime.now(timezone.utc).isoformat(),
                     observations=[first.observed_at.isoformat(), second.observed_at.isoformat()],
                     account_facts_sha256=digest([str(v) for v in empty_account._account_facts(second_account)]))
        # The canonical writer context rolls back both rows on any exception.
        for cursor, state in ((alpaca._DB_CURSOR, current), (CURSOR, {'receipt': value, 'hmac_sha256': _signature(value)})):
            result = conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,CURRENT_DATE,%s::jsonb) ON CONFLICT DO NOTHING',
                                  (cursor, canonical_json(state)))
            if result.rowcount != 1:
                raise Refused('initial paper recovery lost the atomic anchor claim')
        conn.commit()
        return dict(value, resumed=False)
