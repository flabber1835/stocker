"""Bind the PAPER issuer policy to retained references and the existing gateway.

This reads only the small, immutable TICKERS acquisition part. It neither reads
price history nor makes a provider request. The executor owns the writer lock.
"""
from __future__ import annotations

import hashlib
import json

from sentinel.execution import issuer_admission as admission, journal
from sentinel.execution.contract import Side
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.states import CommandState, IN_FLIGHT
from sentinel.feed.rolling_contract import digest


def policy_selected(conn, binding):
    """Enrollment stays selected even when its bytes, policy or epoch refuse."""
    from sentinel import local_paper

    admission._lock(conn)
    if local_paper.enabled():
        return True
    key = admission.ENROLLMENT_PREFIX + admission._scope(binding)
    return conn.execute('SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name=%s',
        (key,)).fetchone() is not None


def reference_instruments(conn, publication):
    from sentinel.feed import alpaca_identity, rolling_store
    from sentinel.feed.operational_snapshot import _bound

    bound = _bound(conn, publication)
    row = conn.execute(
        "SELECT b.part_id,p.manifest,p.reference_payload,p.canonical_reference "
        "FROM sentinel_acquisition_bindings b JOIN sentinel_acquisition_parts p "
        "USING(part_id) WHERE b.job_id=%s AND b.component='TICKERS'",
        (bound['job_id'],)).fetchone()
    if row is None:
        raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_PART_ABSENT')
    part_id, manifest, payload, encoded = row
    if (not isinstance(manifest, dict) or digest(manifest) != part_id
            or manifest.get('component') != 'TICKERS'
            or manifest.get('schema') not in ('sentinel.acquisition-part/1',
                                            'sentinel.acquisition-part/2')):
        raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_PART_CHANGED')
    if encoded is not None:
        expected = manifest.get('reference_sha256', manifest.get('content_sha256'))
        if (not isinstance(encoded, str) or payload is not None
                or len(encoded.encode('utf-8')) > 32 * 1024 * 1024
                or hashlib.sha256(encoded.encode('utf-8')).hexdigest() != expected):
            raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_BYTES_CHANGED')
        payload = json.loads(encoded)
    if (not isinstance(payload, dict) or digest(payload) != manifest.get('content_sha256')
            or (manifest['schema'].endswith('/2')
                and digest(payload) != manifest.get('reference_sha256'))):
        raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_CONTENT_CHANGED')
    reference = rolling_store.load_evidence(
        conn, publication.evidence['rolling_snapshot']['reference_sha256'])
    if reference.get('schema') not in ('sentinel.rolling-alpaca-openfigi-references/2',
                                        'sentinel.rolling-alpaca-openfigi-references/3'):
        raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_IDENTITY_SCHEMA_CHANGED')
    inherited = {value.provider_asset_id: value
        for value in alpaca_identity.bindings(reference.get('identity_bindings', []))}
    selected = payload.get('selected')
    if not isinstance(selected, list):
        raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_SELECTED_COVERAGE_ABSENT')
    result, native_ids, symbols = {}, set(), set()
    for item in selected:
        if (not isinstance(item, dict)
                or not isinstance(item.get('asset_id'), str) or not item['asset_id']
                or not isinstance(item.get('ticker'), str) or not item['ticker']):
            raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_NATIVE_IDENTITY_INVALID')
        asset_id = item['asset_id']
        binding = inherited.get(asset_id)
        if binding is not None and binding.ticker != item['ticker']:
            raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_NATIVE_IDENTITY_CHANGED')
        sid = binding.security_id if binding is not None else asset_id
        if sid in result or asset_id in native_ids or item['ticker'] in symbols:
            raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_NATIVE_IDENTITY_AMBIGUOUS')
        native_ids.add(asset_id)
        symbols.add(item['ticker'])
        result[sid] = admission.Instrument(
            security_id=sid, provider_asset_id=asset_id, symbol=item['ticker'],
            exchange=item.get('exchange'), security_type=item.get('security_type'),
            security_type2=item.get('security_type2'))
    if not result:
        raise admission.IssuerAdmissionRefused('ISSUER_REFERENCE_SELECTED_COVERAGE_ABSENT')
    return result


def _relevant_instruments(conn, *, binding, state, plan, projection, reconciliation,
                          instruments, commands):
    identifiers = {episode.security_id for episode in admission._episodes(state)}
    identifiers.update(plan.target_basket)
    identifiers.update(projection.target_basket)
    identifiers.update(item.security_id for item in plan.opening_intents)
    observation = reconciliation.observation
    if observation is not None:
        identifiers.update(position.instrument.security_id for position in observation.positions)
        identifiers.update(order.instrument.security_id for order in observation.orders)
    identifiers.update(command.security_id for command in commands
        if command.state in IN_FLIGHT or command.state is CommandState.PLANNED
        or command.filled_quantity > 0
        and reconciliation.expected.get(command.security_id, 0) > 0)
    identifiers.update(claim.episode.security_id
        for claim in admission._claims(conn, admission._binding(binding)).values())
    return {sid: item for sid, item in instruments.items() if sid in identifiers}


class PaperIssuerAdmission:
    """One execution attempt; failed setup defers only affected BUYs."""

    def __init__(self, *, conn, binding, clock):
        self.conn, self.binding, self.clock = conn, binding, clock
        self.evidence = None
        self.reconciliation = None
        self.error = 'ISSUER_ADMISSION_CONTEXT_NOT_PREPARED'

    def prepare_for_transport(self, *, publication, state, plan, projection, reconciliation):
        """Finish pre-command metadata before fresh broker guards can write.

        The caller owns this boundary and keeps its session writer/source locks.
        Issuer reservations are made later, with durable command admission.
        """
        self.prepare(publication=publication,state=state,plan=plan,
                     projection=projection,reconciliation=reconciliation)
        self.conn.commit()

    def prepare(self, *, publication, state, plan, projection, reconciliation):
        from sentinel.feed.alpaca_transport import AlpacaTransportRefused
        from sentinel.feed.issuer_reference import load_snapshot
        from sentinel.feed.operational_snapshot import OperationalSnapshotRefused
        from sentinel.feed.rolling_store import SnapshotStorageRefused

        self.reconciliation = reconciliation
        try:
            commands = tuple(journal.load_commands(self.conn, self.binding))
            # A retained plan keeps its original authenticated reference version.
            # A later retry must not replace its economics or episode evidence.
            try:
                self.evidence = admission.load_plan_evidence(
                    self.conn, plan=plan, projection=projection)
            except admission.IssuerAdmissionRefused as exc:
                if str(exc) != 'ISSUER_ADMISSION_PLAN_EVIDENCE_ABSENT':
                    raise
                self.evidence = admission.prepare_plan_evidence(
                    self.conn, binding=self.binding, state=state, plan=plan,
                    projection=projection, reconciliation=reconciliation,
                    snapshot=load_snapshot(),
                    instruments=_relevant_instruments(self.conn, binding=self.binding,
                        state=state, plan=plan, projection=projection,
                        reconciliation=reconciliation, commands=commands,
                        instruments=reference_instruments(self.conn, publication)),
                    now=self.clock(), commands=commands)
            if (self.evidence.binding != admission._binding(self.binding)
                    or self.evidence.canonical_state_sha256 != state.state_hash):
                raise admission.IssuerAdmissionRefused('ISSUER_ADMISSION_PLAN_BINDING_CHANGED')
            if reconciliation.clean:
                admission.release_ended_claims(
                    self.conn, binding=self.binding, state=state,
                    reconciliation=reconciliation, now=self.clock(), commands=commands)
            self.error = None
        except (ValueError, OSError, AlpacaTransportRefused,
                OperationalSnapshotRefused, SnapshotStorageRefused) as exc:
            self.evidence = None
            self.error = f'ISSUER_ADMISSION_UNAVAILABLE: {type(exc).__name__}: {exc}'

    def check_buy(self, *, security_id, reconciliation, instruments, reserve=False):
        self.reconciliation = reconciliation
        if self.evidence is None:
            return admission.Decision(allowed=False, reason=self.error,
                                      security_id=security_id)
        descriptor = self.evidence.instruments.get(security_id)
        native = instruments.get(security_id)
        if (descriptor is None or native is None or descriptor.symbol != native.symbol
                or descriptor.provider_asset_id != native.broker_id):
            return admission.Decision(allowed=False,
                reason='ISSUER_ADMISSION_NATIVE_IDENTITY_CHANGED', security_id=security_id)
        decision = admission.check_buy(
            self.conn, evidence=self.evidence, security_id=security_id,
            reconciliation=reconciliation, now=self.clock(), reserve=reserve)
        if decision.allowed is not True:
            # A shortfall is independent metadata. An admitted reservation
            # stays uncommitted until the executor saves its durable command.
            self.conn.commit()
        return decision

    def final_check(self, *, client_key, instrument, side, quantity, order_terms):
        if side is Side.SELL or instrument.security_id == admission.DEFENSIVE_SECURITY_ID:
            return admission.Decision(allowed=True, reason='REDUCTION_OR_SLEEVE',
                                      security_id=instrument.security_id)
        if self.evidence is None or self.reconciliation is None:
            raise OrderEvidenceNotReady(self.error or 'ISSUER_ADMISSION_CONTEXT_NOT_PREPARED')
        commands = journal.load_commands(self.conn, self.binding)
        matches = [command for command in commands if command.client_key == client_key]
        if (len(matches) != 1 or matches[0].instrument != instrument
                or matches[0].side is not side or matches[0].quantity != quantity
                or matches[0].order_terms != order_terms
                or matches[0].state is not CommandState.SEND_PENDING
                or matches[0].identity.plan_id != self.evidence.plan_id
                or matches[0].identity.deployment != self.binding):
            raise admission.IssuerAdmissionRefused('ISSUER_ADMISSION_DURABLE_COMMAND_CHANGED')
        decision = admission.final_command_check(
            self.conn, evidence=self.evidence, command=matches[0],
            reconciliation=self.reconciliation, now=self.clock(), commands=commands)
        if decision.allowed is not True:
            raise OrderEvidenceNotReady(decision.reason)
        return decision
