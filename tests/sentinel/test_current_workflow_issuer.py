"""Private issuer inputs exercise the real parser; they confer no real identity."""
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel.execution.issuer_admission import Instrument
from sentinel.feed import issuer_reference as reference
from tests.support import current_workflow_issuer as fixture

NOW=datetime(2026,10,28,13,25,tzinfo=timezone.utc)


def instruments():
    return {str(index):Instrument(security_id=str(index),provider_asset_id='native-'+str(index),
        symbol=f'T{index:03d}',exchange='NASDAQ',security_type='Common Stock',
        security_type2='Common Stock') for index in range(500)}


def install(monkeypatch,tmp_path):
    return fixture.install_generated_reference(instruments(),now=NOW,
        monkeypatch=monkeypatch,tmp_path=tmp_path)


def test_generated_listings_have_distinct_verified_issuers_from_retained_bytes(monkeypatch,tmp_path):
    source=install(monkeypatch,tmp_path)
    assert reference.load_snapshot()==source
    identities=[source.resolve(item.symbol,item.exchange,item.security_type,
        item.security_type2,now=NOW) for item in instruments().values()]
    assert all(identity.status=='VERIFIED' and identity.snapshot_digest==source.sha256
               for identity in identities)
    assert len({identity.issuer_id for identity in identities})==500
    assert reference.BUNDLED_PATH.parent==tmp_path
    assert source.provenance.coverage=='PARTIAL'
    assert source.provenance.raw_http_sha256 is None


def test_generated_reference_cannot_cover_unknown_or_expired_listings(monkeypatch,tmp_path):
    source=install(monkeypatch,tmp_path)
    assert source.resolve('T999','NASDAQ','Common Stock','Common Stock',now=NOW).status=='UNRESOLVED'
    assert source.resolve('T000','NASDAQ','Common Stock','Common Stock',
                          now=NOW+timedelta(days=31)).status=='UNRESOLVED'


def test_generated_reference_requires_its_exact_trusted_digest(monkeypatch,tmp_path):
    install(monkeypatch,tmp_path)
    monkeypatch.setattr(reference,'BUNDLED_SNAPSHOT_SHA256','f'*64)
    with pytest.raises(ValueError,match='expected trusted digest'):
        reference.load_snapshot()


def test_removing_private_input_digest_guard_is_detected(monkeypatch,tmp_path):
    source=inspect.getsource(reference.load_snapshot)
    guard='snapshot.snapshot_digest != trusted'
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'False'),'<private issuer digest falsifier>','exec'),
         reference.__dict__,namespace)
    monkeypatch.setattr(reference,'load_snapshot',namespace['load_snapshot'])
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):
        test_generated_reference_requires_its_exact_trusted_digest(monkeypatch,tmp_path)


def test_private_enrollment_cannot_target_an_operational_database(monkeypatch):
    def forbidden(_conn):
        pytest.fail('private enrollment attempted an operational database read')
    monkeypatch.setattr(fixture.binding,'require',forbidden)
    conn=SimpleNamespace(info=SimpleNamespace(dbname='sentinel'))
    with pytest.raises(AssertionError):
        fixture.enroll_generated_account(conn,campaign=None,clock=None,observation_id='fixture')


def test_removing_private_database_boundary_is_detected(monkeypatch):
    source=inspect.getsource(fixture.enroll_generated_account)
    guard="    assert conn.info.dbname.startswith('operational_')"
    assert source.count(guard)==1
    namespace={}
    exec(compile(source.replace(guard,'    pass'),'<private database boundary falsifier>','exec'),
         fixture.__dict__,namespace)
    monkeypatch.setattr(fixture,'enroll_generated_account',namespace['enroll_generated_account'])
    with pytest.raises(pytest.fail.Exception,match='operational database read'):
        test_private_enrollment_cannot_target_an_operational_database(monkeypatch)
