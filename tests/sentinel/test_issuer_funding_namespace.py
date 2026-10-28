"""The funding owner delegates metadata keys without delegating cash authority."""
from contextlib import contextmanager
import inspect
import json
from types import SimpleNamespace

import pytest

from sentinel.execution import issuer_admission as admission, protected_funding as funding
from tests.sentinel.test_limit_day_funding import funding_basis


class NoSql:
    def cursor(self):
        raise AssertionError('reserved namespace reached funding SQL')

    def execute(self, *_args, **_kwargs):
        raise AssertionError('reserved namespace reached funding SQL')


class FundingRows:
    def __init__(self):
        self.rows = {}
        self.selected = None

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, args):
        assert 'WHERE cursor_name=%s' in sql
        self.selected = args[0]

    def fetchone(self):
        return self.rows.get(self.selected)


def test_five_distinct_typed_children_are_inside_the_existing_operational_owner():
    expected = tuple(funding.PREFIX + 'issuer-policy:v1:' + kind + ':'
                     for kind in ('enrollment', 'source', 'plan', 'claim', 'shortfall'))
    assert admission.PREFIXES == expected
    assert funding.ISSUER_POLICY_PREFIX == funding.PREFIX + 'issuer-policy:v1:'
    assert not set(admission.PREFIXES).intersection(admission.LEGACY_PREFIXES)


@pytest.mark.parametrize('suffix', ['issuer-policy:', 'issuer-policy:v1:enrollment:account',
    'issuer-policy:v1:source:digest', 'issuer-policy:v2:claim:account', 'issuer-policy:future'])
def test_funding_reader_rejects_the_whole_reserved_plan_branch_before_sql(suffix):
    with pytest.raises(funding.ProtectedFundingRefused, match='reserved issuer-policy'):
        funding.load_basis(NoSql(), plan_id=suffix)


@pytest.mark.parametrize('suffix', ['issuer-policy:v1:plan:any', 'issuer-policy:v9:shortfall:any'])
def test_funding_writer_rejects_the_whole_reserved_branch_before_sql(suffix):
    with pytest.raises(funding.ProtectedFundingRefused, match='reserved issuer-policy'):
        funding.record_quiescent_basis(NoSql(), plan=SimpleNamespace(plan_id=suffix),
            projection=None, binding=None, reconciliation=None, account=None,
            activity_state=None, observed_at=None, paper_base_url='https://paper-api.alpaca.markets')


def test_funding_roundtrip_remains_exact_and_does_not_enumerate_issuer_rows():
    conn = FundingRows()
    basis = funding_basis(plan_id='sentinel-' + 'a'*64)
    body = basis.model_dump(mode='json')
    body['funding_sha256'] = funding._sha(body)
    conn.rows[funding._funding_key(basis.plan_id)] = (basis.effective_session, json.loads(json.dumps(body)))
    for prefix in admission.PREFIXES:
        conn.rows[prefix + 'unrelated'] = (basis.effective_session, {'issuer': 'not monetary evidence'})
    assert funding.load_basis(conn, plan_id=basis.plan_id) == basis
    assert conn.selected == funding.PREFIX + basis.plan_id
    assert funding.load_basis(conn, plan_id='missing-plan') is None


def test_decoders_cannot_confuse_a_cash_basis_with_an_issuer_envelope():
    basis = funding_basis()
    cash = basis.model_dump(mode='json')
    cash['funding_sha256'] = funding._sha(cash)
    with pytest.raises(admission.IssuerAdmissionRefused, match='RECORD_DIGEST_CHANGED'):
        admission._decode(cash, 'source')
    issuer = {'schema': 'sentinel.issuer-operational-record/1', 'kind': 'source',
              'body': {'issuer_id': 'SEC_CIK:0000000001'}}
    from sentinel.feed.rolling_contract import digest
    issuer['sha256'] = digest({'kind': issuer['kind'], 'body': issuer['body']})
    conn = FundingRows()
    conn.rows[funding._funding_key('p')] = (basis.effective_session, issuer)
    with pytest.raises(funding.ProtectedFundingRefused, match='basis is corrupt'):
        funding.load_basis(conn, plan_id='p')


def test_reserved_branch_rejection_has_a_removed_guard_falsifier(monkeypatch):
    raw = inspect.getsource(funding._funding_key)
    needle = 'or plan_id.startswith(ISSUER_POLICY_BRANCH)'
    assert raw.count(needle) == 1
    namespace = dict(vars(funding))
    exec(compile(raw.replace(needle, 'or False'), 'missing-funding-namespace-guard', 'exec'), namespace)
    monkeypatch.setattr(funding, '_funding_key', namespace['_funding_key'])
    with pytest.raises(AssertionError, match='reached funding SQL'):
        test_funding_reader_rejects_the_whole_reserved_plan_branch_before_sql('issuer-policy:v1:source:any')
