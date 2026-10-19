"""Canonical dual sizing must return its exact detached equity commitment."""
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import psycopg
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


def canonical_authority(conn, equity):
    state, original = case(entries=1, exposure="0.55")
    state.last_evidence["wealth_core"]["estimated_equity"] = equity
    binding, publication, account, observation = _binding(), _publication(), _account(), _observation()
    rollout = RolloutState(RolloutMode.CONTROLLER, 4, certificate_sha256="a" * 64)
    marks, tickers = {"SEC-AAA": D(100), "SENTINEL:BIL": D(100)}, {"SEC-AAA": "AAA", "SENTINEL:BIL": "BIL"}
    plan = decision.build_execution_plan(state=state, binding=binding, publication=publication,
        account_snapshot=account, observation=observation, marks=marks, tickers=tickers,
        decision_session=original.decision_session, effective_session=original.effective_session,
        rollout_state=rollout).plan
    shadow = SimpleNamespace(state=state, record_sha256="b" * 64, runtime_authority_sha256="c" * 64)
    authority = sizing.build_authority(plan=plan, shadow_result=shadow, publication=publication,
        account_snapshot=account, observation=observation, marks=marks, tickers=tickers)
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
