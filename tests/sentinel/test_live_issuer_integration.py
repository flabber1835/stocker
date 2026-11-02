"""LIVE has independent issuer enrollment while reusing canonical admission."""
import pytest

from sentinel.execution import issuer_admission as guard, issuer_refresh, issuer_runtime
from sentinel.execution.identity import DeploymentIdentity
from tests.sentinel import test_issuer_admission as fixtures
from tests.sentinel.test_issuer_admission import source, store  # noqa: F401

LIVE = DeploymentIdentity('issuer-test', 'alpaca-live', '11111111-1111-1111-1111-111111111111', 3)


def test_live_policy_is_separate_without_changing_paper_digest():
    assert guard.policy_sha256(fixtures.BINDING) == guard.POLICY_SHA256
    assert guard.policy_sha256(LIVE) == guard.LIVE_POLICY_SHA256
    assert guard.LIVE_POLICY_SHA256 != guard.POLICY_SHA256


def test_paper_enrollment_cannot_authorize_live_namespace(store, source):
    fixtures.enroll(store, source)
    with pytest.raises(guard.IssuerAdmissionRefused, match='NOT_ENROLLED'):
        guard.load_enrollment(store, binding=LIVE)


def test_live_enrollment_never_grandfathers_native_stock_holdings(store, source, monkeypatch):
    monkeypatch.setattr(fixtures, 'BINDING', LIVE)
    with pytest.raises(guard.IssuerAdmissionRefused, match='REQUIRES_EMPTY_BOOK'):
        fixtures.enroll(store, source, 'A')


def test_live_enrollment_and_reserved_stock_buy_use_distinct_policy(store, source, monkeypatch):
    monkeypatch.setattr(fixtures, 'BINDING', LIVE)
    enrollment = fixtures.enroll(store, source)
    assert enrollment.policy_sha256 == guard.LIVE_POLICY_SHA256
    assert enrollment.episodes == ()
    _, _, _, evidence = fixtures.prepare(store, source, pending=('A',))
    assert evidence.policy_sha256 == guard.LIVE_POLICY_SHA256
    decision = fixtures.buy(store, evidence, 'A', reserve=True)
    assert decision.allowed
    assert all(claim.policy_sha256 == guard.LIVE_POLICY_SHA256
               for claim in guard._claims(store, guard._binding(LIVE)).values())


def test_live_rejects_paper_policy_even_under_live_account_key(store, source, monkeypatch):
    monkeypatch.setattr(fixtures, 'BINDING', LIVE)
    fixtures.enroll(store, source)
    original = guard._read
    def wrong_policy(conn, key, kind):
        value = original(conn, key, kind)
        return {**value, 'policy_sha256': guard.POLICY_SHA256} if kind == 'enrollment' else value
    monkeypatch.setattr(guard, '_read', wrong_policy)
    with pytest.raises(guard.IssuerAdmissionRefused, match='BINDING_CHANGED'):
        guard.load_enrollment(store, binding=LIVE)


def test_live_issuer_policy_stays_selected_without_enrollment(store, monkeypatch):
    monkeypatch.setattr(issuer_runtime.admission, '_lock', lambda _c: None)
    monkeypatch.setattr('sentinel.local_paper.enabled', lambda: pytest.fail('PAPER exemption entered LIVE'))
    assert issuer_runtime.policy_selected(store, LIVE) is True


def test_live_issuer_refresh_reads_only_exact_live_enrollment(monkeypatch):
    from sentinel import binding, local_paper
    from sentinel.binding import AccountBinding
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    bound = AccountBinding(**LIVE.to_dict())
    monkeypatch.setattr(binding, 'require', lambda _c: bound)
    monkeypatch.setattr(local_paper, 'bound_account', lambda _c: pytest.fail('PAPER owner entered LIVE'))
    seen = []
    monkeypatch.setattr(guard, 'load_enrollment', lambda conn, **kw: seen.append(kw))
    result = issuer_refresh._owner(object())
    assert result.broker == 'alpaca-live'
    assert seen == [{'binding': result}]
