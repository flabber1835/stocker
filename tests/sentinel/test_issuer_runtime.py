"""Retained reference and final command integration for the PAPER issuer gate."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel.execution import issuer_admission as admission, issuer_runtime as runtime
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, OrderTerms, Side
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.states import CommandState
from sentinel.feed import operational_snapshot, rolling_store
from sentinel.feed.rolling_contract import canonical_json, digest

NOW = datetime(2026, 10, 27, 13, 31, tzinfo=timezone.utc)
BINDING = DeploymentIdentity('issuer-runtime', 'alpaca', 'PAFIXTURE', 1)
NATIVE = BrokerInstrument('canonical', 'CLASS.A', 'native-asset')


def part_reader(monkeypatch, *, schema='sentinel.acquisition-part/2', encoded=False,
                selected=None, identity_bindings=None):
    payload = {'selected': selected if selected is not None else [
        {'asset_id': 'native-asset', 'ticker': 'CLASS.A', 'exchange': 'NYSE',
         'security_type': 'Common Stock', 'security_type2': 'Common Stock'}]}
    manifest = {'schema': schema, 'job_id': 'bound-job', 'component': 'TICKERS',
        'content_sha256': digest(payload)}
    if schema.endswith('/2'):
        manifest['reference_sha256'] = digest(payload)
    h = SimpleNamespace(row=[digest(manifest), manifest,
        None if encoded else payload, canonical_json(payload) if encoded else None], queries=[], references=[])

    class Connection:
        def execute(self, statement, parameters):
            h.queries.append((statement, parameters))
            return SimpleNamespace(fetchone=lambda: h.row)

    monkeypatch.setattr(operational_snapshot, '_bound',
        lambda _conn, _publication: {'job_id': 'bound-job'})

    def load(_conn, identity):
        h.references.append(identity)
        return {'schema': 'sentinel.rolling-alpaca-openfigi-references/3',
            'identity_bindings': identity_bindings or []}

    monkeypatch.setattr(rolling_store, 'load_evidence', load)
    h.conn = Connection()
    h.publication = SimpleNamespace(evidence={'rolling_snapshot': {'reference_sha256': 'b'*64}})
    return h


@pytest.mark.parametrize('schema', ['sentinel.acquisition-part/1', 'sentinel.acquisition-part/2'])
@pytest.mark.parametrize('encoded', [False, True])
def test_reference_loader_authenticates_complete_part_without_price_or_provider_read(monkeypatch, schema, encoded):
    h = part_reader(monkeypatch, schema=schema, encoded=encoded)
    result = runtime.reference_instruments(h.conn, h.publication)
    assert result['native-asset'].provider_asset_id == 'native-asset'
    assert result['native-asset'].symbol == 'CLASS.A'
    assert len(h.queries) == 1 and h.queries[0][1] == ('bound-job',)
    assert h.references == ['b'*64]
    assert 'sentinel_acquisition_prices' not in h.queries[0][0]


@pytest.mark.parametrize('damage', ['manifest_digest', 'component', 'payload', 'reference', 'bytes'])
def test_reference_loader_refuses_changed_manifest_content_and_bytes(monkeypatch, damage):
    h = part_reader(monkeypatch, encoded=damage == 'bytes')
    if damage == 'manifest_digest':h.row[0] = 'a'*64
    elif damage == 'component':
        h.row[1]['component'] = 'unbound'
        h.row[0] = digest(h.row[1])
    elif damage == 'payload':h.row[2]['selected'][0]['ticker'] = 'REUSED'
    elif damage == 'reference':
        h.row[1]['reference_sha256'] = 'a'*64
        h.row[0] = digest(h.row[1])
    else:h.row[3] += ' '
    with pytest.raises(admission.IssuerAdmissionRefused):
        runtime.reference_instruments(h.conn, h.publication)


def test_current_binding_can_reuse_an_authenticated_parent_job_reference_part(monkeypatch):
    h = part_reader(monkeypatch)
    h.row[1]['job_id'] = 'retained-parent-job'
    h.row[0] = digest(h.row[1])
    result = runtime.reference_instruments(h.conn, h.publication)
    assert result['native-asset'].symbol == 'CLASS.A'
    assert h.queries[0][1] == ('bound-job',)


def test_reference_loader_projects_authenticated_provider_identity_to_canonical_security(monkeypatch):
    binding = dict(security_id='canonical', provider_asset_id='native-asset',
        prior_provider_asset_id='old-native', ticker='CLASS.A', origin_snapshot_id='a'*64,
        event=dict(id='event', old_symbol='CLASS.A', new_symbol='CLASS.A',
            old_cusip='111111111', new_cusip='222222222', process_date='2026-10-26'))
    h = part_reader(monkeypatch, identity_bindings=[binding])
    result = runtime.reference_instruments(h.conn, h.publication)
    assert set(result) == {'canonical'}
    assert result['canonical'].provider_asset_id == 'native-asset'


@pytest.mark.parametrize('selected', [
    [{'asset_id': 'one', 'ticker': 'A'}, {'asset_id': 'one', 'ticker': 'B'}],
    [{'asset_id': 'one', 'ticker': 'A'}, {'asset_id': 'two', 'ticker': 'A'}],
    [{'ticker': 'A'}], [None],
])
def test_reference_loader_refuses_ambiguous_or_malformed_selected_identity(monkeypatch, selected):
    h = part_reader(monkeypatch, selected=selected)
    with pytest.raises(admission.IssuerAdmissionRefused):
        runtime.reference_instruments(h.conn, h.publication)


def context(monkeypatch):
    h = SimpleNamespace(commands=[], calls=[])
    h.evidence = SimpleNamespace(binding=admission._binding(BINDING),
        canonical_state_sha256='a'*64, plan_id='plan',
        instruments={'canonical': admission.Instrument(security_id='canonical',
            provider_asset_id='native-asset', symbol='CLASS.A')})
    h.rec = SimpleNamespace(clean=True, expected={}, observation=None)
    h.value = runtime.PaperIssuerAdmission(conn=object(), binding=BINDING, clock=lambda: NOW)
    monkeypatch.setattr(runtime.journal, 'load_commands', lambda *_args: tuple(h.commands))
    monkeypatch.setattr(admission, 'release_ended_claims', lambda *_args, **kwargs: h.calls.append(('release', kwargs)))
    return h


def test_retry_reuses_retained_plan_source_and_does_not_load_new_reference(monkeypatch):
    from sentinel.feed import issuer_reference
    h = context(monkeypatch)
    monkeypatch.setattr(admission, 'load_plan_evidence', lambda *_args, **_kwargs: h.evidence)
    monkeypatch.setattr(issuer_reference, 'load_snapshot', lambda: pytest.fail('retry reloaded source'))
    monkeypatch.setattr(runtime, 'reference_instruments', lambda *_args: pytest.fail('retry reread full part'))
    h.value.prepare(publication=object(), state=SimpleNamespace(state_hash='a'*64),
        plan=object(), projection=object(), reconciliation=h.rec)
    assert h.value.evidence is h.evidence and h.value.error is None
    assert h.calls[0][0] == 'release'


def test_missing_enrollment_defers_buy_and_final_guard_raises_before_transport(monkeypatch):
    from sentinel.feed import issuer_reference
    h = context(monkeypatch)

    def absent(*_args, **_kwargs):
        raise admission.IssuerAdmissionRefused('ISSUER_ADMISSION_PLAN_EVIDENCE_ABSENT')

    def unenrolled(*_args, **_kwargs):
        raise admission.IssuerAdmissionRefused('ISSUER_ADMISSION_NOT_ENROLLED')

    monkeypatch.setattr(admission, 'load_plan_evidence', absent)
    monkeypatch.setattr(admission, 'prepare_plan_evidence', unenrolled)
    monkeypatch.setattr(issuer_reference, 'load_snapshot', lambda: object())
    monkeypatch.setattr(runtime, 'reference_instruments', lambda *_args: {})
    monkeypatch.setattr(runtime, '_relevant_instruments', lambda *_args, **_kwargs: {})
    h.value.prepare(publication=object(), state=object(), plan=object(),
        projection=object(), reconciliation=h.rec)
    result = h.value.check_buy(security_id='canonical', reconciliation=h.rec,
        instruments={'canonical': NATIVE})
    assert result.allowed is False and 'NOT_ENROLLED' in result.reason
    assert not h.calls
    with pytest.raises(OrderEvidenceNotReady, match='NOT_ENROLLED'):
        h.value.final_check(client_key='key', instrument=NATIVE, side=Side.BUY,
            quantity=Decimal(1), order_terms=OrderTerms())


def test_per_security_restriction_does_not_attempt_global_claim_release(monkeypatch):
    h = context(monkeypatch)
    h.rec.clean = False
    monkeypatch.setattr(admission, 'load_plan_evidence', lambda *_args, **_kwargs: h.evidence)
    h.value.prepare(publication=object(), state=SimpleNamespace(state_hash='a'*64),
        plan=object(), projection=object(), reconciliation=h.rec)
    assert h.value.evidence is h.evidence and h.value.error is None
    assert not h.calls


@pytest.mark.parametrize('damage', ['native_asset', 'symbol', 'absent'])
def test_buy_check_refuses_native_asset_or_symbol_mismatch(monkeypatch, damage):
    h = context(monkeypatch)
    h.value.evidence = h.evidence
    monkeypatch.setattr(admission, 'check_buy', lambda *_args, **_kwargs: pytest.fail('mismatch reached policy'))
    native = replace(NATIVE, broker_id='other') if damage == 'native_asset' else replace(NATIVE, symbol='REUSED')
    result = h.value.check_buy(security_id='canonical', reconciliation=h.rec,
        instruments={} if damage == 'absent' else {'canonical': native})
    assert not result.allowed and result.reason == 'ISSUER_ADMISSION_NATIVE_IDENTITY_CHANGED'


def durable_command(*, plan='plan', state=CommandState.SEND_PENDING):
    return Command(CommandIdentity(BINDING, plan, 'canonical'), NATIVE,
        Side.BUY, Decimal(2), state=state)


def final_context(monkeypatch, *, allowed=True):
    h = context(monkeypatch)
    h.value.evidence = h.evidence
    h.value.reconciliation = h.rec
    h.commands = [durable_command()]

    def check(_conn, **kwargs):
        h.calls.append(('final', kwargs))
        return admission.Decision(allowed=allowed,
            reason='ADMITTED_EPISODE' if allowed else 'ISSUER_CONFLICT', security_id='canonical')

    monkeypatch.setattr(admission, 'final_command_check', check)
    h.submit = lambda: h.value.final_check(client_key=h.commands[0].client_key,
        instrument=NATIVE, side=Side.BUY, quantity=Decimal(2), order_terms=OrderTerms())
    return h


def test_final_callback_binds_durable_command_and_rechecks_current_decision(monkeypatch):
    h = final_context(monkeypatch)
    assert h.submit().allowed is True
    call = h.calls[0][1]
    assert call['command'] is h.commands[0] and call['evidence'] is h.evidence
    assert call['commands'] == tuple(h.commands) and call['reconciliation'] is h.rec


@pytest.mark.parametrize('damage', ['plan', 'binding', 'state', 'instrument', 'quantity', 'duplicate', 'missing'])
def test_final_callback_rejects_changed_command_identity_plan_and_economics(monkeypatch, damage):
    h = final_context(monkeypatch)
    key = h.commands[0].client_key
    if damage == 'plan':h.commands[0] = durable_command(plan='other-plan')
    elif damage == 'binding':
        command = h.commands[0]
        h.commands[0] = replace(command, identity=replace(command.identity,
            deployment=replace(BINDING, takeover_epoch=2)))
    elif damage == 'state':h.commands[0] = durable_command(state=CommandState.PLANNED)
    elif damage == 'instrument':h.commands[0] = replace(h.commands[0], instrument=replace(NATIVE, broker_id='other'))
    elif damage == 'quantity':h.commands[0] = replace(h.commands[0], quantity=Decimal(3))
    elif damage == 'duplicate':h.commands.append(h.commands[0])
    else:h.commands.clear()
    if damage in ('plan', 'binding'):
        h.commands[0] = replace(h.commands[0], recovered_key=key)
    with pytest.raises(admission.IssuerAdmissionRefused, match='DURABLE_COMMAND_CHANGED'):
        h.value.final_check(client_key=key, instrument=NATIVE, side=Side.BUY,
            quantity=Decimal(2), order_terms=OrderTerms())
    assert not h.calls


def test_final_denied_decision_raises_the_guarded_pretransport_type(monkeypatch):
    h = final_context(monkeypatch, allowed=False)
    with pytest.raises(OrderEvidenceNotReady, match='ISSUER_CONFLICT'):
        h.submit()


def test_final_denial_handling_has_a_falsifier(monkeypatch):
    source = textwrap.dedent(inspect.getsource(runtime.PaperIssuerAdmission.final_check))
    needle = 'if decision.allowed is not True:'
    assert source.count(needle) == 1
    namespace = dict(vars(runtime))
    exec(compile(source.replace(needle, 'if False:'), 'missing-final-issuer-denial', 'exec'), namespace)
    monkeypatch.setattr(runtime.PaperIssuerAdmission, 'final_check', namespace['final_check'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_final_denied_decision_raises_the_guarded_pretransport_type(monkeypatch)


def test_relevant_descriptors_cover_account_claims_and_canonical_intent_without_universe_copy(monkeypatch):
    identifiers = {'episode', 'pending', 'target', 'projection', 'opening', 'position',
        'order', 'planned', 'unknown', 'filled-held', 'claim'}
    descriptors = {sid: object() for sid in identifiers | {'unrelated', 'old-filled'}}
    state = SimpleNamespace(wealth_core={'episodes': {'one': dict(security_id='episode',
        current_shares='1', slot_id=0, signal_date='2026-10-01')}},
        pending=[dict(operation='OPEN_SLOT_POSITION', security_id='pending', slot_id=1,
            signal_session='2026-10-26')])
    instrument = lambda sid: SimpleNamespace(security_id=sid)
    rec = SimpleNamespace(expected={'filled-held': Decimal(1)},
        observation=SimpleNamespace(positions=[SimpleNamespace(instrument=instrument('position'))],
            orders=[SimpleNamespace(instrument=instrument('order'))]))
    commands = [SimpleNamespace(security_id=sid, state=status, filled_quantity=Decimal(filled))
        for sid, status, filled in [('planned', CommandState.PLANNED, 0),
            ('unknown', CommandState.UNKNOWN, 0), ('filled-held', CommandState.FILLED, 1),
            ('old-filled', CommandState.FILLED, 1)]]
    monkeypatch.setattr(admission, '_claims', lambda *_args: {
        'key': SimpleNamespace(episode=SimpleNamespace(security_id='claim'))})
    result = runtime._relevant_instruments(object(), binding=BINDING, state=state,
        plan=SimpleNamespace(target_basket={'target': 1}, opening_intents=[instrument('opening')]),
        projection=SimpleNamespace(target_basket={'projection': 1}), reconciliation=rec,
        instruments=descriptors, commands=commands)
    assert set(result) == identifiers
    assert len(descriptors) == len(identifiers) + 2


@pytest.mark.parametrize('present', [False, True])
def test_durable_account_policy_selection_uses_presence_even_when_record_is_invalid(monkeypatch, present):
    from sentinel import local_paper
    calls = []
    monkeypatch.setattr(local_paper, 'enabled', lambda: False)
    monkeypatch.setattr(admission, '_lock', lambda conn: calls.append(('lock', conn)))
    monkeypatch.setattr(admission, 'load_enrollment',
        lambda *_args, **_kwargs: pytest.fail('selection tried to validate malformed enrollment'))
    conn = SimpleNamespace()

    def execute(statement, parameters):
        assert calls == [('lock', conn)]
        calls.append((statement, parameters))
        return SimpleNamespace(fetchone=lambda: (1,) if present else None)

    conn.execute = execute
    assert runtime.policy_selected(conn, BINDING) is present
    assert calls[1] == ('SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name=%s',
        (admission.ENROLLMENT_PREFIX + admission._scope(BINDING),))


def test_local_paper_policy_is_selected_before_enrollment_and_without_issuer_read(monkeypatch):
    from sentinel import local_paper
    locked = []
    monkeypatch.setattr(local_paper, 'enabled', lambda: True)
    monkeypatch.setattr(admission, '_lock', lambda conn: locked.append(conn))
    conn = SimpleNamespace(execute=lambda *_args: pytest.fail('local selection read enrollment'))
    assert runtime.policy_selected(conn, BINDING) is True
    assert locked == [conn]


def test_takeover_epoch_cannot_disable_an_existing_account_policy(monkeypatch):
    from sentinel import local_paper
    keys = []
    monkeypatch.setattr(local_paper, 'enabled', lambda: False)
    monkeypatch.setattr(admission, '_lock', lambda _conn: None)

    def execute(_statement, parameters):
        keys.append(parameters[0])
        return SimpleNamespace(fetchone=lambda: (1,))

    conn = SimpleNamespace(execute=execute)
    assert runtime.policy_selected(conn, BINDING)
    assert runtime.policy_selected(conn, replace(BINDING, takeover_epoch=2))
    assert keys[0] == keys[1]
