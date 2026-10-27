"""Account entry admission from retained issuer evidence; never edits the shadow.

Every write is append-only and requires execution's existing session writer lock.
The caller owns the transaction: a reservation and its command admission must
commit together. No function here performs provider I/O or broker transport.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from sentinel.execution import journal
from sentinel.execution.contract import Side
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.states import CommandState, IN_FLIGHT, RuntimeState
from sentinel.feed.issuer_reference import IssuerReferenceSnapshot
from sentinel.feed.rolling_contract import Digest, digest

ENROLLMENT_PREFIX = 'issuer-admission-enrollment:v1:'
SOURCE_PREFIX = 'issuer-reference-snapshot:v1:'
PLAN_PREFIX = 'issuer-plan-admission:v1:'
CLAIM_PREFIX = 'issuer-episode-claim:v1:'
SHORTFALL_PREFIX = 'issuer-entry-shortfall:v1:'
PREFIXES = (ENROLLMENT_PREFIX, SOURCE_PREFIX, PLAN_PREFIX, CLAIM_PREFIX, SHORTFALL_PREFIX)
DEFENSIVE_SECURITY_ID = 'SENTINEL:BIL'
POLICY = 'SEC_OPERATING_ISSUER_NEW_PAPER_EPISODE_V1'
POLICY_SHA256 = digest({'policy': POLICY, 'baseline': 'ONCE_POSITIVELY_ATTRIBUTED_EPISODES',
    'unknown_incumbent': 'BLOCK_NEW_EPISODES', 'source_max_age_days': 30,
    'winner': 'CANONICAL_SLOT_SECURITY_ORDER', 'targets': 'PRESERVE_POSITIVE_INTENT'})


class IssuerAdmissionRefused(ValueError):
    pass


class _Typed(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Binding(_Typed):
    deployment_id: str = Field(min_length=1)
    broker: str = Field(min_length=1)
    broker_account_id: str = Field(min_length=1)
    takeover_epoch: int = Field(ge=0, strict=True)


class Episode(_Typed):
    security_id: str = Field(min_length=1)
    slot_id: int = Field(ge=0, strict=True)
    signal_date: date

    @property
    def key(self):
        return digest(self.model_dump(mode='json'))


class Instrument(_Typed):
    security_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    provider_asset_id: str = Field(min_length=1)
    exchange: str | None = None
    security_type: str | None = None
    security_type2: str | None = None


class Enrollment(_Typed):
    schema_id: Literal['sentinel.issuer-admission-enrollment/1'] = 'sentinel.issuer-admission-enrollment/1'
    binding: Binding
    policy_sha256: Digest = POLICY_SHA256
    canonical_state_sha256: Digest
    observation_id: int = Field(gt=0, strict=True)
    observation_sha256: Digest
    source_snapshot_sha256: Digest
    enrolled_at: datetime
    episodes: tuple[Episode, ...]
    native_positions: dict[str, dict]
    excluded_unsent_proofs: tuple[dict, ...] = ()

    @property
    def sha256(self):
        return digest(self.model_dump(mode='json'))


class PlanEvidence(_Typed):
    schema_id: Literal['sentinel.issuer-plan-admission/1'] = 'sentinel.issuer-plan-admission/1'
    binding: Binding
    policy_sha256: Digest = POLICY_SHA256
    enrollment_sha256: Digest
    canonical_state_sha256: Digest
    plan_id: str = Field(min_length=1)
    plan_fingerprint: Digest
    projection_fingerprint: Digest
    source_snapshot_sha256: Digest
    decision_session: date
    effective_session: date
    episodes: tuple[Episode, ...]
    instruments: dict[str, Instrument]
    target_basket: dict[str, str]
    opening_intents: tuple[dict, ...] = ()

    @property
    def sha256(self):
        return digest(self.model_dump(mode='json'))


class Decision(_Typed):
    allowed: bool
    reason: str
    security_id: str
    issuer_id: str | None = None
    episode_keys: tuple[str, ...] = ()
    conflicting_security_ids: tuple[str, ...] = ()


class Claim(_Typed):
    schema_id: Literal['sentinel.issuer-episode-claim/1'] = 'sentinel.issuer-episode-claim/1'
    binding: Binding
    enrollment_sha256: Digest
    policy_sha256: Digest = POLICY_SHA256
    episode: Episode
    issuer_id: str = Field(pattern=r'^SEC_CIK:[0-9]{10}$')
    plan_evidence_sha256: Digest
    source_snapshot_sha256: Digest
    reserved_at: datetime


class Release(_Typed):
    schema_id: Literal['sentinel.issuer-episode-release/1'] = 'sentinel.issuer-episode-release/1'
    binding: Binding
    policy_sha256: Digest = POLICY_SHA256
    episode_key: Digest
    reservation_sha256: Digest
    canonical_state_sha256: Digest
    observation_sha256: Digest
    observation_id: int = Field(gt=0, strict=True)
    released_at: datetime


class Shortfall(_Typed):
    schema_id: Literal['sentinel.issuer-entry-shortfall/1'] = 'sentinel.issuer-entry-shortfall/1'
    binding: Binding
    policy_sha256: Digest = POLICY_SHA256
    plan_evidence_sha256: Digest
    plan_id: str
    security_id: str
    decision: Decision
    observation_sha256: Digest
    desired: str
    held: str
    committed: str
    unmet_quantity: str


def _binding(binding):
    return Binding.model_validate(binding.to_dict() if hasattr(binding, 'to_dict') else binding)


def _scope(binding):
    # Epoch is deliberately absent from the key: a takeover cannot reseed an
    # account's grandfather list. The stored exact epoch must still agree.
    raw = _binding(binding).model_dump(mode='json')
    raw.pop('takeover_epoch')
    return digest(raw)


def _now(now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_AWARE_TIME_REQUIRED')
    return now.astimezone(timezone.utc)


def _lock(conn):
    row = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid()"
        " AND locktype='advisory' AND classid=0 AND objid=%s"
        " AND objsubid=1 AND mode='ExclusiveLock' AND granted)", (journal.WRITER_LOCK_KEY,)).fetchone()
    if row is None or row[0] is not True:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_WRITER_LOCK_REQUIRED')


def _append(conn, key, session, kind, body):
    record = {'schema': 'sentinel.issuer-operational-record/1', 'kind': kind,
              'body': body, 'sha256': digest({'kind': kind, 'body': body})}
    old = _read(conn, key, kind)
    if old is not None:
        if old != body:
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_IMMUTABLE_RECORD_CHANGED:' + key)
        return
    import json
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state)'
        ' VALUES (%s,%s,%s::jsonb) ON CONFLICT(cursor_name) DO NOTHING',
        (key, session, json.dumps(record, sort_keys=True, separators=(',', ':'))))
    if _read(conn, key, kind) != body:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_CONCURRENT_RECORD_CHANGED')


def _decode(raw, kind=None):
    if (not isinstance(raw, dict) or set(raw) != {'schema', 'kind', 'body', 'sha256'}
            or raw['schema'] != 'sentinel.issuer-operational-record/1'
            or not isinstance(raw['body'], dict)
            or (kind is not None and raw['kind'] != kind)
            or raw['sha256'] != digest({'kind': raw['kind'], 'body': raw['body']})):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_RECORD_DIGEST_CHANGED')
    return raw['body']


def _read(conn, key, kind):
    row = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (key,)).fetchone()
    return None if row is None else _decode(row[0], kind)


def _records(conn, prefix):
    rows = conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions'
        ' WHERE cursor_name >= %s AND cursor_name < %s ORDER BY cursor_name LIMIT 10001',
        (prefix, prefix + '~')).fetchall()
    if len(rows) > 10000:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_RECORD_LIMIT')
    result = []
    for key, raw in rows:
        body = _decode(raw)
        result.append((key, raw['kind'], body))
    return result


def _episodes(state):
    values = {}
    for raw in state.wealth_core['episodes'].values():
        if Decimal(str(raw['current_shares'])) > 0:
            ep = Episode(security_id=str(raw['security_id']), slot_id=int(raw['slot_id']),
                         signal_date=raw['signal_date'])
            values[ep.key] = ep
    for raw in state.pending:
        if raw['operation'] == 'OPEN_SLOT_POSITION':
            ep = Episode(security_id=str(raw['security_id']), slot_id=int(raw['slot_id']),
                         signal_date=raw['signal_session'])
            values[ep.key] = ep
    return tuple(sorted(values.values(), key=lambda ep: (ep.slot_id, ep.security_id, ep.signal_date)))


def _instruments(raw):
    result = {}
    for sid, item in raw.items():
        if sid == DEFENSIVE_SECURITY_ID:
            continue
        if isinstance(item, Instrument):
            value = item
        else:
            value = Instrument(security_id=sid, symbol=item.get('symbol', item.get('ticker')),
                provider_asset_id=item.get('provider_asset_id', item.get('asset_id')),
                exchange=item.get('exchange'), security_type=item.get('security_type'),
                security_type2=item.get('security_type2'))
        if value.security_id != sid:
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_NATIVE_IDENTITY_CHANGED')
        result[sid] = value
    return result


def _reconciliation(binding, rec, now, *, clean=False):
    observation = getattr(rec, 'observation', None)
    if (rec.runtime_state is not RuntimeState.RUNNING or observation is None
            or not observation.is_complete or rec.observation_id is None
            or (clean and not rec.clean) or not rec.transport_ready
            or observation.account_identity is None
            or not DeploymentIdentity(**binding.model_dump()).matches_account(observation.account_identity)
            or observation.observed_at > now):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_COMPLETE_ACCOUNT_RECONCILIATION_REQUIRED')
    positions = observation.positions_by_security()
    if any(not qty.is_finite() or qty < 0 for qty in positions.values()):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_LONG_ONLY_OBSERVATION_REQUIRED')
    facts = {'observation_id': rec.observation_id, 'observed_at': observation.observed_at.isoformat(),
        'account': {'broker': observation.account_identity.broker,
                    'account_id': observation.account_identity.account_id},
        'positions': {sid: str(qty) for sid, qty in sorted(positions.items())},
        'orders': [{'key': order.client_key, 'id': order.broker_order_id,
                    'security_id': order.instrument.security_id, 'state': order.state.value,
                    'quantity': str(order.quantity), 'filled': str(order.filled_quantity)}
                   for order in observation.orders]}
    return observation, facts


def _commands(conn, binding, commands):
    values = tuple(journal.load_commands(conn, DeploymentIdentity(**binding.model_dump()))
                   if commands is None else commands)
    for command in values:
        owner = command.identity.deployment
        if (owner.deployment_id != binding.deployment_id or owner.broker != binding.broker
                or owner.broker_account_id != binding.broker_account_id
                or owner.takeover_epoch > binding.takeover_epoch):
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_COMMAND_ACCOUNT_CHANGED')
    return values


def _unsent_proof(conn, command, observation, now):
    """Positive journal-only no-transport proof for an obsolete PLANNED row."""
    if (command.state is not CommandState.PLANNED or command.filled_quantity != 0
            or command.broker_order_id is not None
            or any(o.client_key == command.client_key for o in observation.orders)):
        return None
    plan = journal.load_plan(conn, command.identity.plan_id)
    from zoneinfo import ZoneInfo
    if plan is None or (not plan.is_superseded and plan.effective_session >= now.astimezone(ZoneInfo('America/New_York')).date()):
        return None
    history = journal.command_history(conn, command.client_key)
    if (not history or history[0]['from'] is not None or history[0]['to'] != 'PLANNED'):
        return None
    pending = False
    for item in history:
        if Decimal(str(item.get('filled') or 0)) != 0:
            return None
        before, after = item['from'], item['to']
        if after == 'PLANNED' and before is None and not pending:
            continue
        if before == 'PLANNED' and after == 'SEND_PENDING' and not pending:
            pending = True
        elif (pending and before == 'SEND_PENDING' and after == 'PLANNED'
              and str(item.get('detail', '')).startswith('PRE_TRANSPORT_CHECKPOINT_RESTORED: ')):
            pending = False
        else:
            return None
    if pending or history[-1]['to'] != 'PLANNED':
        return None
    return {'client_key': command.client_key, 'plan_id': command.identity.plan_id,
        'plan_fingerprint': plan.fingerprint(), 'events_sha256': digest([
            {k: str(v) if isinstance(v, (datetime, Decimal)) else v for k, v in row.items()}
            for row in history]), 'observation_sha256': digest({'at': observation.observed_at.isoformat(),
            'orders': [o.client_key for o in observation.orders]})}


def load_enrollment(conn, *, binding):
    owner = _binding(binding)
    raw = _read(conn, ENROLLMENT_PREFIX + _scope(owner), 'enrollment')
    if raw is None:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_NOT_ENROLLED')
    value = Enrollment.model_validate(raw)
    if value.binding != owner or value.policy_sha256 != POLICY_SHA256:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_ENROLLMENT_BINDING_CHANGED')
    return value


def _store_source(conn, snapshot, session):
    snapshot = IssuerReferenceSnapshot.model_validate(snapshot)
    _append(conn, SOURCE_PREFIX + snapshot.snapshot_digest, session, 'source', snapshot.model_dump(mode='json'))
    return snapshot


def enroll(conn, *, binding, state, reconciliation, snapshot, instruments, now, commands=None):
    """Explicit one-time enrollment; existing accounts can never be reseeded."""
    _lock(conn)
    owner, now = _binding(binding), _now(now)
    key = ENROLLMENT_PREFIX + _scope(owner)
    if _read(conn, key, 'enrollment') is not None:
        existing = load_enrollment(conn, binding=owner)
        if existing.canonical_state_sha256 != state.state_hash:
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_RESEED_FORBIDDEN')
        return existing
    observation, facts = _reconciliation(owner, reconciliation, now, clean=True)
    descriptors = _instruments(instruments)
    excluded = []
    for command in _commands(conn, owner, commands):
        if command.state in IN_FLIGHT:
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_ENROLLMENT_COMMAND_PENDING')
        if command.state is CommandState.PLANNED:
            proof = _unsent_proof(conn, command, observation, now)
            if proof is None:
                raise IssuerAdmissionRefused('ISSUER_ADMISSION_ENROLLMENT_COMMAND_POSSIBLY_EFFECTIVE')
            excluded.append(proof)
    if any(order.is_working for order in observation.orders):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_ENROLLMENT_WORKING_ORDER')
    held = {str(ep['security_id']) for ep in state.wealth_core['episodes'].values()
            if Decimal(str(ep['current_shares'])) > 0}
    native = {}
    for position in observation.positions:
        sid, quantity = position.instrument.security_id, position.quantity
        if quantity <= 0 or sid == DEFENSIVE_SECURITY_ID:
            continue
        descriptor = descriptors.get(sid)
        if (sid not in held or reconciliation.expected.get(sid, Decimal(0)) != quantity
                or descriptor is None or not position.instrument.broker_id
                or descriptor.provider_asset_id != position.instrument.broker_id
                or descriptor.symbol != position.instrument.symbol):
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_GENUINE_ATTRIBUTED_HOLDING_REQUIRED')
        native[sid] = {'quantity': str(quantity), 'symbol': descriptor.symbol,
                       'provider_asset_id': descriptor.provider_asset_id}
    source = _store_source(conn, snapshot, date.fromisoformat(state.last_processed_session))
    baseline = tuple(ep for ep in _episodes(state) if ep.security_id in native
        and any(int(raw['slot_id']) == ep.slot_id and raw['signal_date'] == str(ep.signal_date)
                for raw in state.wealth_core['episodes'].values()))
    value = Enrollment(binding=owner, canonical_state_sha256=state.state_hash,
        observation_id=reconciliation.observation_id, observation_sha256=digest(facts),
        source_snapshot_sha256=source.snapshot_digest, enrolled_at=now,
        episodes=baseline, native_positions=native,
        excluded_unsent_proofs=tuple(sorted(excluded, key=lambda row: row['client_key'])))
    _append(conn, key, now.date(), 'enrollment', value.model_dump(mode='json'))
    return value


def _plan_key(evidence):
    return PLAN_PREFIX + evidence.plan_id + ':' + evidence.projection_fingerprint


def load_plan_evidence(conn, *, plan, projection):
    raw = _read(conn, PLAN_PREFIX + plan.plan_id + ':' + projection.fingerprint(), 'plan')
    if raw is None:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_PLAN_EVIDENCE_ABSENT')
    value, _ = _validate_evidence(conn, PlanEvidence.model_validate(raw))
    if (value.plan_fingerprint != plan.fingerprint()
            or value.projection_fingerprint != projection.fingerprint()):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_PLAN_BINDING_CHANGED')
    return value


def prepare_plan_evidence(conn, *, binding, state, plan, projection, reconciliation,
                          snapshot, instruments, now, commands=None):
    _lock(conn)
    owner, now = _binding(binding), _now(now)
    enrollment = load_enrollment(conn, binding=owner)
    _reconciliation(owner, reconciliation, now)
    _commands(conn, owner, commands)
    if (state.state_hash != plan.shadow_snapshot_hash
            or projection.plan_id != plan.plan_id or projection.plan_fingerprint != plan.fingerprint()
            or projection.through_session != plan.effective_session
            or any(getattr(plan, field) != getattr(owner, field) for field in Binding.model_fields)):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_PLAN_BINDING_CHANGED')
    source = _store_source(conn, snapshot, plan.decision_session)
    value = PlanEvidence(binding=owner, enrollment_sha256=enrollment.sha256,
        canonical_state_sha256=state.state_hash, plan_id=plan.plan_id,
        plan_fingerprint=plan.fingerprint(), projection_fingerprint=projection.fingerprint(),
        source_snapshot_sha256=source.snapshot_digest, decision_session=plan.decision_session,
        effective_session=plan.effective_session, episodes=_episodes(state),
        instruments=_instruments(instruments),
        target_basket={sid: str(qty) for sid, qty in sorted(projection.target_basket.items())},
        opening_intents=tuple(item.to_dict() for item in plan.opening_intents))
    _append(conn, _plan_key(value), plan.decision_session, 'plan', value.model_dump(mode='json'))
    return value


def _source(conn, evidence):
    raw = _read(conn, SOURCE_PREFIX + evidence.source_snapshot_sha256, 'source')
    if raw is None:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_SOURCE_ABSENT')
    value = IssuerReferenceSnapshot.model_validate(raw)
    if value.snapshot_digest != evidence.source_snapshot_sha256:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_SOURCE_DIGEST_CHANGED')
    return value


def _resolve(source, descriptors, sid, now):
    item = descriptors.get(sid)
    if item is None:
        return None
    identity = source.resolve(item.symbol, item.exchange, item.security_type, item.security_type2, now=now)
    return identity.issuer_id if identity.status == 'VERIFIED' else None


def _claims(conn, binding):
    prefix = CLAIM_PREFIX + _scope(binding) + ':'
    reserved, released = {}, {}
    for key, kind, raw in _records(conn, prefix):
        if kind == 'reservation':
            claim = Claim.model_validate(raw)
            if claim.binding != binding or claim.policy_sha256 != POLICY_SHA256:
                raise IssuerAdmissionRefused('ISSUER_ADMISSION_CLAIM_BINDING_CHANGED')
            if key != prefix + claim.episode.key + ':reserved':
                raise IssuerAdmissionRefused('ISSUER_ADMISSION_CLAIM_KEY_CHANGED')
            reserved[claim.episode.key] = claim
        elif kind == 'release':
            release = Release.model_validate(raw)
            if (release.binding != binding or release.policy_sha256 != POLICY_SHA256
                    or key != prefix + release.episode_key + ':released'):
                raise IssuerAdmissionRefused('ISSUER_ADMISSION_RELEASE_BINDING_CHANGED')
            released[release.episode_key] = release
        else:
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_CLAIM_KIND_CHANGED')
    if set(released) - set(reserved):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_RELEASE_WITHOUT_RESERVATION')
    for key, release in released.items():
        if release.reservation_sha256 != digest(reserved[key].model_dump(mode='json')):
            raise IssuerAdmissionRefused('ISSUER_ADMISSION_RELEASE_RESERVATION_CHANGED')
    return {key: value for key, value in reserved.items() if key not in released}


def _validate_evidence(conn, evidence):
    value = PlanEvidence.model_validate(evidence)
    if _read(conn, _plan_key(value), 'plan') != value.model_dump(mode='json'):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_PLAN_EVIDENCE_CHANGED')
    enrollment = load_enrollment(conn, binding=value.binding)
    if value.enrollment_sha256 != enrollment.sha256 or value.policy_sha256 != POLICY_SHA256:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_POLICY_CHANGED')
    return value, enrollment


def check_buy(conn, *, evidence, security_id, reconciliation, now, commands=None, reserve=False):
    """Check a BUY; ``reserve=True`` writes its episode claim before transport."""
    _lock(conn)
    now = _now(now)
    value, enrollment = _validate_evidence(conn, evidence)
    observation, facts = _reconciliation(value.binding, reconciliation, now)
    commands = _commands(conn, value.binding, commands)
    if security_id == DEFENSIVE_SECURITY_ID:
        return Decision(allowed=True, reason='DEFENSIVE_SLEEVE', security_id=security_id)
    if Decimal(value.target_basket.get(security_id, '0')) <= 0:
        return Decision(allowed=False, reason='ISSUER_POSITIVE_TARGET_REQUIRED', security_id=security_id)
    own = tuple(ep for ep in value.episodes if ep.security_id == security_id)
    keys = tuple(ep.key for ep in own)
    baseline = {ep.key for ep in enrollment.episodes}
    claims = _claims(conn, value.binding)
    if any(claim.enrollment_sha256 != enrollment.sha256 for claim in claims.values()):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_CLAIM_ENROLLMENT_CHANGED')
    if own and set(keys).issubset(baseline):
        return Decision(allowed=True, reason='GRANDFATHERED_EPISODE', security_id=security_id, episode_keys=keys)
    source = _source(conn, value)
    issuer = _resolve(source, value.instruments, security_id, now)
    reason, conflicts = None, set()
    if not own:
        reason = 'ISSUER_EPISODE_OWNERSHIP_ABSENT'
    elif issuer is None:
        reason = 'ISSUER_IDENTITY_UNRESOLVED'
    incumbents = {claim.episode.security_id for claim in claims.values()}
    continuing = {ep.security_id for ep in value.episodes if ep.key in baseline}
    incumbents.update(continuing)
    incumbents.update(sid for sid, qty in observation.positions_by_security().items() if qty > 0)
    possible_commands = []
    for command in commands:
        if command.side is Side.BUY and (command.state in IN_FLIGHT
                or command.state is CommandState.PLANNED
                and _unsent_proof(conn, command, observation, now) is None
                or command.filled_quantity > 0
                and reconciliation.expected.get(command.security_id, Decimal(0)) > 0):
            incumbents.add(command.security_id)
            possible_commands.append(command)
    possible_orders = [order for order in observation.orders if order.is_working and order.side is Side.BUY]
    incumbents.update(order.instrument.security_id for order in possible_orders)
    approved = bool(own) and all(key in claims for key in keys)
    changed_native = set()
    for position in observation.positions:
        descriptor = value.instruments.get(position.instrument.security_id)
        if position.quantity > 0 and (descriptor is None
                or descriptor.provider_asset_id != position.instrument.broker_id
                or descriptor.symbol != position.instrument.symbol):
            changed_native.add(position.instrument.security_id)
    for item in (*possible_commands, *possible_orders):
        native = item.instrument
        descriptor = value.instruments.get(native.security_id)
        if (descriptor is None or descriptor.provider_asset_id != native.broker_id
                or descriptor.symbol != native.symbol):
            changed_native.add(native.security_id)
    for sid in sorted(incumbents - {DEFENSIVE_SECURITY_ID}):
        current_issuer = None if sid in changed_native else _resolve(source, value.instruments, sid, now)
        if any(claim.episode.security_id == sid and claim.issuer_id != current_issuer
               for claim in claims.values()):
            current_issuer = None
        if sid == security_id and approved:
            # A continuing reservation is valid only with the same verified
            # issuer. Fresh source evidence may not retarget a standing claim.
            if current_issuer is None or any(claims[key].issuer_id != issuer for key in keys):
                reason = 'ISSUER_RESERVED_IDENTITY_CHANGED'
            continue
        if current_issuer is None:
            reason = 'ISSUER_INCUMBENT_UNRESOLVED'
            conflicts.add(sid)
        elif sid == security_id:
            reason = 'ISSUER_UNATTRIBUTED_EPISODE'
            conflicts.add(sid)
        elif current_issuer == issuer:
            if reason != 'ISSUER_INCUMBENT_UNRESOLVED':
                reason = 'ISSUER_CONFLICT'
            conflicts.add(sid)
    if reason is None and not approved:
        entry_slots = {item['security_id']: item['slot_id'] for item in value.opening_intents}
        competitors = {ep.security_id for ep in value.episodes
            if Decimal(value.target_basket.get(ep.security_id, '0')) > 0
            and _resolve(source, value.instruments, ep.security_id, now) == issuer}
        winner = min(competitors, key=lambda sid: (entry_slots.get(sid, 20), sid))
        if winner != security_id:
            reason = 'ISSUER_CANONICAL_PRIORITY_CONFLICT'
            conflicts.add(winner)
    decision = Decision(allowed=reason is None, reason=reason or ('ADMITTED_EPISODE' if approved else 'ISSUER_VERIFIED'),
        security_id=security_id, issuer_id=issuer, episode_keys=keys,
        conflicting_security_ids=tuple(sorted(conflicts)))
    if not decision.allowed:
        target = Decimal(value.target_basket.get(security_id, '0'))
        held = observation.positions_by_security().get(security_id, Decimal(0))
        from sentinel.execution.commands import committed_quantity
        committed = committed_quantity(observation.working_orders_for(security_id))
        shortfall = Shortfall(binding=value.binding, plan_evidence_sha256=value.sha256,
            plan_id=value.plan_id, security_id=security_id, decision=decision,
            observation_sha256=digest(facts), desired=str(target), held=str(held),
            committed=str(committed), unmet_quantity=str(max(Decimal(0), target-held-committed))).model_dump(mode='json')
        _append(conn, SHORTFALL_PREFIX + value.plan_id + ':' + digest(shortfall), value.effective_session,
                'shortfall', shortfall)
    elif reserve:
        for ep in own:
            key = CLAIM_PREFIX + _scope(value.binding) + ':' + ep.key + ':reserved'
            if ep.key in claims:
                continue
            claim = Claim(binding=value.binding, enrollment_sha256=enrollment.sha256,
                episode=ep, issuer_id=issuer, plan_evidence_sha256=value.sha256,
                source_snapshot_sha256=source.snapshot_digest, reserved_at=now)
            _append(conn, key, value.effective_session, 'reservation', claim.model_dump(mode='json'))
    return decision


def final_command_check(conn, *, evidence, command, reconciliation, now, commands=None):
    """Repeat the BUY policy at the last membrane boundary; reductions are free."""
    if command.side is Side.SELL:
        return Decision(allowed=True, reason='REDUCTION', security_id=command.security_id)
    value = PlanEvidence.model_validate(evidence)
    if command.identity.plan_id != value.plan_id or _binding(command.identity.deployment) != value.binding:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_COMMAND_PLAN_CHANGED')
    descriptor = value.instruments.get(command.security_id)
    if command.security_id != DEFENSIVE_SECURITY_ID and (descriptor is None
            or descriptor.symbol != command.instrument.symbol
            or descriptor.provider_asset_id != command.instrument.broker_id):
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_COMMAND_NATIVE_IDENTITY_CHANGED')
    decision = check_buy(conn, evidence=value, security_id=command.security_id,
        reconciliation=reconciliation, now=now, commands=commands, reserve=False)
    if decision.allowed and decision.reason not in {'GRANDFATHERED_EPISODE', 'DEFENSIVE_SLEEVE', 'ADMITTED_EPISODE'}:
        raise IssuerAdmissionRefused('ISSUER_ADMISSION_RESERVATION_REQUIRED_BEFORE_TRANSPORT')
    return decision


def release_ended_claims(conn, *, binding, state, reconciliation, now, commands=None):
    """Append releases only after ended ownership and positively reconciled zero."""
    _lock(conn)
    owner, now = _binding(binding), _now(now)
    load_enrollment(conn, binding=owner)
    observation, facts = _reconciliation(owner, reconciliation, now, clean=True)
    commands = _commands(conn, owner, commands)
    current = {ep.key for ep in _episodes(state)}
    released = []
    for key, claim in _claims(conn, owner).items():
        sid = claim.episode.security_id
        possibly_effective = any(command.security_id == sid and (
            command.state in IN_FLIGHT or command.state is CommandState.PLANNED
            and _unsent_proof(conn, command, observation, now) is None) for command in commands)
        if (key in current or observation.positions_by_security().get(sid, Decimal(0)) != 0
                or reconciliation.expected.get(sid, Decimal(0)) != 0 or possibly_effective
                or any(o.instrument.security_id == sid and o.is_working for o in observation.orders)):
            continue
        body = Release(binding=owner, episode_key=key,
            reservation_sha256=digest(claim.model_dump(mode='json')),
            canonical_state_sha256=state.state_hash, observation_sha256=digest(facts),
            observation_id=reconciliation.observation_id, released_at=now).model_dump(mode='json')
        _append(conn, CLAIM_PREFIX + _scope(owner) + ':' + key + ':released',
                date.fromisoformat(state.last_processed_session), 'release', body)
        released.append(key)
    return tuple(released)
