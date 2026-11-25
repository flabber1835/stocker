"""Canonical dual sizing must return its exact detached equity commitment."""
from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import psycopg
from psycopg.types.json import Jsonb
import pytest

from sentinel import dual_plan_authority as sizing, schema
from sentinel.authority import RolloutMode, RolloutState
from sentinel.core import decision
from tests.sentinel.test_order_terms_schema import pg  # noqa: F401
from tests.sentinel.test_production_decision import _account, _binding, _observation, _publication
from tests.support.postgres import drop_public_tables
from tests.v5.test_opening import case


@pytest.fixture
def conn(pg):
    with psycopg.connect(pg.sync_dsn) as connection:
        drop_public_tables(connection)
        schema.ensure_schema(connection)
        yield connection


def canonical_authority(conn, equity, *, market_policy_sha256=None):
    state, original = case(entries=1, exposure="0.55")
    state.last_evidence["wealth_core"]["estimated_equity"] = equity
    binding, publication, account, observation = _binding(), _publication(), _account(), _observation()
    rollout = RolloutState(RolloutMode.CONTROLLER, 4, certificate_sha256="a" * 64)
    marks, tickers = {"SEC-AAA": D(100), "SENTINEL:BIL": D(100)}, {"SEC-AAA": "AAA", "SENTINEL:BIL": "BIL"}
    from sentinel.execution import held_targets

    share_basis = (None if market_policy_sha256 is None else held_targets.build_basis(
        conn, previous=None, state=state, binding=binding, rollout=rollout))
    plan = decision.build_execution_plan(state=state, binding=binding, publication=publication,
        account_snapshot=account, observation=observation, marks=marks, tickers=tickers,
        decision_session=original.decision_session, effective_session=original.effective_session,
        rollout_state=rollout,
        retained_targets=None if share_basis is None else {}).plan
    shadow = SimpleNamespace(state=state, record_sha256="b" * 64, runtime_authority_sha256="c" * 64)
    authority = sizing.build_authority(plan=plan, shadow_result=shadow, publication=publication,
        account_snapshot=account, observation=observation, marks=marks, tickers=tickers,
        held_share_targets=share_basis, market_buy_policy_sha256=market_policy_sha256)
    stored = sizing.record_authority(conn, authority)
    assert stored == authority and sizing.load_authority(conn, plan_id=plan.plan_id) == authority
    return plan, binding, rollout, shadow, authority


def assert_scalar_proof(conn, fixture, *, equity, expected, derive):
    plan, binding, rollout, shadow, authority = fixture
    before = shadow.state.state_hash
    proof = derive(conn, plan=plan, binding=binding, rollout_state=rollout, expected_shadow_result=shadow)
    assert proof["verdict"] == "MATCH" and proof["schema"] == sizing.SCHEMA
    assert proof["authority_sha256"] == authority["authority_sha256"]
    assert proof["state_sha256"] == before == shadow.state.state_hash == plan.shadow_snapshot_hash
    assert proof["plan_fingerprint"] == plan.fingerprint()
    assert type(proof["shadow_equity"]) is str and proof["shadow_equity"] == expected
    assert D(proof["shadow_equity"]) == D(equity)
    assert sizing.load_authority(conn, plan_id=plan.plan_id) == authority


@pytest.mark.parametrize("equity,expected", [
    ("100000.125000", "100000.125"), ("1E+5", "100000"),
    ("123456789.123456789012345678", "123456789.123456789012345678"),
])
def test_real_canonical_rederivation_returns_exact_equity_scalar(conn, equity, expected):
    fixture = canonical_authority(conn, equity)
    assert_scalar_proof(conn, fixture, equity=equity, expected=expected, derive=sizing._rederive_plan)


def test_missing_numeric_import_falsifier_reaches_real_return_statement(conn):
    equity, expected = "100000.125000", "100000.125"
    fixture = canonical_authority(conn, equity)
    assert_scalar_proof(conn, fixture, equity=equity, expected=expected, derive=sizing._rederive_plan)
    source = Path(sizing.__file__).read_text(encoding="utf-8")
    import_line = "from sentinel.execution.numeric import decimal_text\n"
    assert source.count(import_line) == 1
    namespace = {"__name__": sizing.__name__, "__file__": sizing.__file__}
    exec(compile(source.replace(import_line, ""), "<missing-numeric-import>", "exec"), namespace)
    assert "decimal_text" not in namespace
    with pytest.raises(NameError, match="decimal_text") as refused:
        assert_scalar_proof(conn, fixture, equity=equity, expected=expected, derive=namespace["_rederive_plan"])
    traceback = refused.value.__traceback__
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    assert traceback.tb_frame.f_code.co_name == "_rederive_plan"
    assert traceback.tb_frame.f_locals["derived"].plan.to_dict() == fixture[0].to_dict()


def test_exact_verified_state_avoids_a_second_decode(conn, monkeypatch):
    fixture = canonical_authority(conn, "100000.125")
    plan, bound, rollout, verified, _ = fixture
    kwargs = dict(plan=plan, binding=bound, rollout_state=rollout)
    full = sizing._rederive_plan(conn, expected_shadow_result=None, **kwargs)
    decodes = []
    original = sizing.SessionState.from_dict

    def restore(cls, raw, **kwargs):
        decodes.append(raw)
        return original(raw, **kwargs)

    monkeypatch.setattr(sizing.SessionState, 'from_dict', classmethod(restore))
    assert sizing._rederive_plan(conn, expected_shadow_result=verified, **kwargs) == full
    assert len(decodes) == 1  # The canonical sizing adapter still decodes.
    assert verified.state.state_hash == plan.shadow_snapshot_hash


@pytest.mark.parametrize('case', ['legacy', 'changed_state', 'changed_record'])
def test_state_reuse_keeps_legacy_restore_and_exact_commitments(conn, case):
    from sentinel.core.session import LEGACY_ENVELOPE_VERSIONS

    plan, bound, rollout, verified, authority = canonical_authority(conn, "100000.125")
    changes = deepcopy(authority)
    if case == 'legacy':
        changes['shadow_state']['version'] = max(LEGACY_ENVELOPE_VERSIONS)
    elif case == 'changed_state':
        changes['shadow_state']['last_evidence']['wealth_core']['estimated_equity'] = '90000'
    else:
        changes['shadow_record_sha256'] = 'd' * 64
    changes.pop('authority_sha256')
    changes['authority_sha256'] = sizing._sha256(changes)
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s WHERE cursor_name=%s',
                 (Jsonb(changes), sizing.CURSOR_PREFIX + plan.plan_id))
    kwargs = dict(plan=plan, binding=bound, rollout_state=rollout, expected_shadow_result=verified)
    if case == 'legacy':
        assert sizing._rederive_plan(conn, **kwargs)['state_sha256'] == plan.shadow_snapshot_hash
    else:
        reason = ('differs from the plan commitment' if case == 'changed_state'
                  else 'differs from the plan input')
        with pytest.raises(sizing.DualPlanAuthorityRefused, match=reason):
            sizing._rederive_plan(conn, **kwargs)


def test_new_transport_refuses_cross_policy_plan_reuse_but_preserves_historical_replay(conn, monkeypatch):
    from sentinel.execution.market_buy_policy import MarketBuyPolicy
    from tests.sentinel.test_market_buy_policy import MARKET_ENV

    prior = canonical_authority(conn, "100000")
    for key, value in MARKET_ENV.items():
        monkeypatch.setenv(key, value)
    policy_hash = MarketBuyPolicy().fingerprint()
    with pytest.raises(sizing.DualPlanAuthorityRefused, match="prepare a new decision"):
        sizing.require_current_buy_policy(conn, plan=prior[0])
    assert_scalar_proof(conn, prior, equity="100000", expected="100000", derive=sizing._rederive_plan)

    current = canonical_authority(conn, "100001", market_policy_sha256=policy_hash)
    plan, _, _, _, authority = current
    assert authority["schema"] == sizing.MARKET_SCHEMA
    assert authority["market_buy_policy_sha256"] == policy_hash
    with psycopg.connect(conn.info.dsn) as reopened:
        sizing.require_current_buy_policy(reopened, plan=plan)
        monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", "PROTECTED_LIMIT_DAY_V1")
        monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
        with pytest.raises(sizing.DualPlanAuthorityRefused, match="prepare a new decision"):
            sizing.require_current_buy_policy(reopened, plan=plan)
        sizing.require_current_buy_policy(reopened, plan=prior[0])
        assert_scalar_proof(
            reopened, current, equity="100001", expected="100001", derive=sizing._rederive_plan)
