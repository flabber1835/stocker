"""Bounded SEC acquisition and private durable maintenance; no real provider/broker."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import io
import json
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from scripts import sentinel_env
from sentinel.execution import issuer_admission as admission, issuer_refresh as worker, journal
from sentinel.feed import issuer_reference as reference, issuer_refresh as feed
from tests.sentinel.test_automation_outbox import conn, pg  # noqa: F401
from tests.sentinel.test_issuer_admission import (
    BINDING, NOW, command, instruments, prepare, reconciliation, state,
)

EMAIL = 'operator@example.test'


def source():
    return reference.IssuerReferenceSnapshot.create(observed_at_utc=NOW,
        associations=[dict(cik='0000000001',ticker='AAA',exchange='NYSE'),
                      dict(cik='0000000001',ticker='AAA-A',exchange='NYSE'),
                      dict(cik='0000000002',ticker='BBB',exchange='NYSE')],
        corroborations=reference.load_snapshot().corroborations)


def payload(rows=None):
    return json.dumps({'fields':['cik','name','ticker','exchange'],
        'data':rows or [[1,'name is not identity','AAA','NYSE'],[1,'same issuer','AAA-A','NYSE'],[2,'other','BBB','NYSE']]}).encode()


DISCLOSURE = b'''<html><body>Our common and preferred shares without par value PBR/PBRA NYSE.
American Depositary Shares, or ADSs, each representing two of our common or preferred shares.
Our common and preferred shares are not convertible into one another.</body></html>'''


class Reply(io.BytesIO):
    status=200


class Opener:
    def __init__(self, raw=None, *, status=None, disclosure=DISCLOSURE, callback=None):
        self.raw=raw or payload();self.status=status;self.disclosure=disclosure;self.calls=[];self.callback=callback

    def open(self, request, timeout):
        self.calls.append((request.full_url,timeout,request.get_header('User-agent')))
        if self.callback:self.callback(request)
        if self.status:raise HTTPError(request.full_url,self.status,'private provider text',{},None)
        return Reply(self.raw if request.full_url==reference.SEC_ENDPOINT else self.disclosure)


@pytest.mark.parametrize('value',[EMAIL,'a.b+client@example.org','operator@sub.example.org'])
def test_contact_is_validated_identically_by_literal_host_and_runtime(value):
    sentinel_env._sec_contact({feed.CONTACT_ENV:value})
    assert value in feed.declared_user_agent(value)


@pytest.mark.parametrize('value',['','x','x@y','x@example.org\nInjected: bad',' x@example.org','x@example.org ',
    'x\r@example.org','x..y@example.org','x.@example.org','x@-example.org','x@exämple.org','x'*65+'@example.org'])
def test_invalid_contacts_refuse_without_printing_them(value):
    with pytest.raises(ValueError) as error:feed.declared_user_agent(value)
    assert value not in str(error.value) if len(value)>25 else True
    if value:
        with pytest.raises(sentinel_env.EnvRefused):sentinel_env._sec_contact({feed.CONTACT_ENV:value})


def test_two_exact_official_reads_prove_pbr_underlying_and_record_real_body_hashes():
    previous=source();client=Opener()
    result=feed.refresh(previous,email=EMAIL,anchors=previous.associations,now=NOW,opener=client)
    assert result.status=='REFRESHED' and len(client.calls)==2
    assert [call[0] for call in client.calls]==[reference.SEC_ENDPOINT,feed.PETROBRAS_URL]
    assert all(call[1]==4 for call in client.calls)
    assert result.snapshot.provenance.raw_http_sha256==hashlib.sha256(payload()).hexdigest()
    proof=result.snapshot.corroborations[0]
    assert hashlib.sha256(DISCLOSURE).hexdigest() in proof.statement
    assert proof.observed_at_utc==NOW and proof.expires_at_utc==NOW+timedelta(days=30)
    assert proof.observation_time_basis=='CONSERVATIVE_PRIOR_UTC_BOUND'
    assert EMAIL not in result.model_dump_json()
    assert previous.corroborations[0].observed_at_utc < proof.observed_at_utc


@pytest.mark.parametrize('fault',['missing_ads','wrong_ratio','script_only','missing_conversion','oversize','foreign_url'])
def test_bad_or_untrusted_disclosure_does_not_renew_corroboration(fault):
    previous=source().corroborations[0]
    raw=DISCLOSURE
    if fault=='missing_ads':raw=raw.replace(b'American Depositary Shares',b'Unrelated securities')
    if fault=='wrong_ratio':raw=raw.replace(b'each representing two',b'each representing one')
    if fault=='script_only':raw=b'<script>'+DISCLOSURE+b'</script>'
    if fault=='missing_conversion':raw=raw.replace(b'not convertible',b'convertible')
    if fault=='oversize':raw=b'x'*(reference.MAX_RESPONSE_BYTES+1)
    if fault=='foreign_url':previous=previous.model_copy(update={'source_url':'https://example.test/disclosure'})
    with pytest.raises(ValueError):feed.disclosure_proof(raw,previous=previous,now=NOW)


def test_failed_disclosure_keeps_its_original_expiry_and_requests_hourly_retry():
    previous=source();result=feed.refresh(previous,email=EMAIL,anchors=previous.associations,now=NOW,
        opener=Opener(disclosure=b'<html>no evidence</html>'))
    assert result.status=='REFRESHED' and result.snapshot.corroborations==previous.corroborations
    assert result.reason.endswith('unavailable') and result.retry_after_seconds==3600


def test_positive_adr_renewal_preserves_pbr_and_pbr_a_as_one_issuer_after_old_expiry():
    proof=reference.load_snapshot().corroborations[0]
    previous=reference.IssuerReferenceSnapshot.create(observed_at_utc=NOW,associations=[
        dict(cik='0001119639',ticker=symbol,exchange='NYSE') for symbol in ('PBR','PBR-A')],
        corroborations=[proof])
    later=NOW+timedelta(days=31)
    raw=payload([[1119639,'Petrobras','PBR','NYSE'],[1119639,'Petrobras','PBR-A','NYSE']])
    current=feed.refresh(previous,email=EMAIL,anchors=previous.associations,now=later,opener=Opener(raw)).snapshot
    for symbol in ('PBR','PBR.A'):
        assert previous.resolve(symbol,'NYSE','ADR','Depositary Receipt',now=later).status=='UNRESOLVED'
        assert worker.Eligibility(previous,current,()).resolve(symbol,'NYSE','ADR','Depositary Receipt',now=later).issuer_id=='SEC_CIK:0001119639'
    assert previous.corroborations==(proof,)


def test_first_seen_anchor_survives_disappearance_and_changed_cik_cannot_be_laundered():
    prior=source()
    first=reference.refresh_snapshot(prior,now=NOW,opener=Opener(payload([[2,'other','BBB','NYSE']])),anchor_rows=prior.associations)
    assert first.status=='REFRESHED'
    assert any(row.ticker=='AAA' for row in first.anchor_rows)
    changed=reference.refresh_snapshot(first.snapshot,now=NOW,opener=Opener(payload([[9,'reused','AAA','NYSE'],[2,'other','BBB','NYSE']])),anchor_rows=first.anchor_rows)
    assert changed.snapshot.provenance.coverage=='PARTIAL' and changed.quarantined_symbols==('AAA',)
    assert changed.snapshot.resolve('AAA','NYSE','Common Stock','Common Stock',now=NOW).status=='UNRESOLVED'
    retried=reference.refresh_snapshot(changed.snapshot,now=NOW,opener=Opener(),
        anchor_rows=changed.anchor_rows,quarantined_symbols=changed.quarantined_symbols)
    assert retried.quarantined_symbols==('AAA',)
    assert all(row.ticker!='AAA' for row in retried.snapshot.associations)


def test_ambiguous_dot_hyphen_and_cross_exchange_conflicts_are_quarantined():
    prior=source()
    rows=[reference.IssuerAssociation(cik='0000000001',ticker='AAA.A',exchange='NYSE'),
          reference.IssuerAssociation(cik='0000000001',ticker='AAA-A',exchange='NYSE'),
          reference.IssuerAssociation(cik='0000000009',ticker='BBB',exchange='Nasdaq')]
    selected,anchors,blocked=feed.quarantine_observation(rows,prior.associations,())
    assert not selected and set(blocked)=={'AAA-A','BBB'}
    assert prior.associations[0] in anchors


def setup(conn,monkeypatch):
    previous=source()
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(journal.WRITER_LOCK_KEY,))
    admission.enroll(conn,binding=BINDING,state=state(),reconciliation=reconciliation(),snapshot=previous,
                     instruments=instruments(),now=NOW,commands=())
    conn.commit()
    from sentinel import local_paper
    monkeypatch.setattr(local_paper,'bound_account',lambda conn:SimpleNamespace(identity=BINDING))
    monkeypatch.setattr(worker,'_opening_delay',lambda now:0)
    monkeypatch.setattr(reference,'load_snapshot',lambda:previous)
    return previous


def test_native_refresh_persists_restart_backoff_and_avoids_unchanged_full_versions(conn,monkeypatch):
    previous=setup(conn,monkeypatch);client=Opener()
    result=worker.collect(conn,email=EMAIL,now=NOW,opener=client)
    assert result['status']=='REFRESHED'
    state1,catalog1,version1=worker._load(conn,BINDING,previous)
    assert version1.provenance.source_method=='DIRECT_HTTP_BODY'
    assert state1.last_success_at==NOW
    client.calls.clear()
    assert worker.collect(conn,email=EMAIL,now=NOW+timedelta(seconds=1),opener=client)['status']=='CACHED'
    assert not client.calls
    assert worker.collect(conn,email=EMAIL,now=NOW+timedelta(days=1),opener=client)['status']=='REFRESHED'
    state2,catalog2,version2=worker._load(conn,BINDING,previous)
    assert version2.snapshot_digest==version1.snapshot_digest and catalog2.sha256==catalog1.sha256
    assert state2.last_success_at==NOW+timedelta(days=1)
    assert version2.provenance.expires_at_utc==version1.provenance.expires_at_utc
    assert len(client.calls)==2
    other=__import__('sentinel.feed.store',fromlist=['connect']).connect(conn.info.dsn)
    try:
        assert worker._load(other,BINDING,previous)[0].sha256==state2.sha256
    finally:other.close()


@pytest.mark.parametrize('http_status',[403,429,503])
def test_native_failure_never_renews_valid_cache_or_retries_before_durable_deadline(conn,monkeypatch,http_status):
    previous=setup(conn,monkeypatch);client=Opener(status=http_status)
    result=worker.collect(conn,email=EMAIL,now=NOW,opener=client)
    assert result['status']=='CACHED_VALID' and len(client.calls)==1
    current,catalog,retained=worker._load(conn,BINDING,previous)
    assert retained==previous and current.last_success_at is None
    client.calls.clear()
    assert worker.collect(conn,email=EMAIL,now=NOW+timedelta(minutes=30),opener=client)['status']=='CACHED'
    assert not client.calls


def test_http_runs_without_execution_writer_lock_or_open_transaction(conn,monkeypatch):
    setup(conn,monkeypatch)
    from sentinel.feed import store
    fresh=store.connect(conn.info.dsn)
    def during_http(_request):
        assert conn.info.transaction_status.value==0
        assert fresh.execute('SELECT pg_try_advisory_xact_lock(%s)',(journal.WRITER_LOCK_KEY,)).fetchone()[0] is True
        fresh.rollback()
    try:assert worker.collect(conn,email=EMAIL,now=NOW,opener=Opener(callback=during_http))['status']=='REFRESHED'
    finally:fresh.close()


def test_native_active_writer_defers_without_provider_access(conn,monkeypatch):
    setup(conn,monkeypatch)
    from sentinel.feed import store
    other=store.connect(conn.info.dsn)
    try:
        other.execute('SELECT pg_advisory_xact_lock(%s)',(journal.WRITER_LOCK_KEY,))
        client=Opener()
        assert worker.collect(conn,email=EMAIL,now=NOW,opener=client)['status']=='DEFERRED'
        assert not client.calls
    finally:other.rollback();other.close()


def test_native_foreign_epoch_during_http_refuses_publication_and_keeps_backoff(conn,monkeypatch):
    previous=setup(conn,monkeypatch)
    from sentinel import local_paper
    changed=SimpleNamespace(**{**BINDING.to_dict(),'takeover_epoch':4})
    changed.to_dict=lambda:{**BINDING.to_dict(),'takeover_epoch':4}
    def mutate(_request):monkeypatch.setattr(local_paper,'bound_account',lambda conn:SimpleNamespace(identity=changed))
    with pytest.raises(admission.IssuerAdmissionRefused):worker.collect(conn,email=EMAIL,now=NOW,opener=Opener(callback=mutate))
    current,_catalog,retained=worker._load(conn,BINDING,previous)
    assert retained==previous and current.reason=='attempt_started' and current.last_success_at is None


def test_actual_opening_window_skips_io_and_is_not_a_weekend_hardcode():
    from datetime import datetime,timezone
    assert worker._opening_delay(datetime(2026,11,2,14,30,tzinfo=timezone.utc))==600
    assert worker._opening_delay(datetime(2026,11,2,14,41,tzinfo=timezone.utc))==0
    assert worker._opening_delay(datetime(2026,11,1,14,30,tzinfo=timezone.utc))==0


def test_retained_plan_can_use_fresh_same_issuer_but_not_unknown_or_changed_identity():
    old=source();later=NOW+timedelta(days=31)
    current=reference.IssuerReferenceSnapshot.create(observed_at_utc=later,associations=[*old.associations,
        dict(cik='0000000004',ticker='UNKNOWN',exchange='NYSE')])
    view=worker.Eligibility(old,current,())
    assert view.resolve('AAA','NYSE','Common Stock','Common Stock',now=later).issuer_id=='SEC_CIK:0000000001'
    assert view.resolve('UNKNOWN','NYSE','Common Stock','Common Stock',now=later).status=='UNRESOLVED'
    assert worker.Eligibility(old,current,('AAA',)).resolve('AAA','NYSE','Common Stock','Common Stock',now=later).status=='UNRESOLVED'
    changed=reference.IssuerReferenceSnapshot.create(observed_at_utc=later,associations=[dict(cik='0000000009',ticker='AAA',exchange='NYSE')])
    assert worker.Eligibility(old,changed,()).resolve('AAA','NYSE','Common Stock','Common Stock',now=later).status=='UNRESOLVED'


def test_executed_removed_historical_agreement_guard_is_detected(monkeypatch):
    old=source();later=NOW+timedelta(days=31)
    changed=reference.IssuerReferenceSnapshot.create(observed_at_utc=later,associations=[dict(cik='0000000009',ticker='AAA',exchange='NYSE')])
    def assertion():assert worker.Eligibility(old,changed,()).resolve('AAA','NYSE','Common Stock','Common Stock',now=later).status=='UNRESOLVED'
    assertion()
    monkeypatch.setattr(worker.Eligibility,'resolve',lambda self,*args,**kw:self.current.resolve(*args,**kw))
    with pytest.raises(AssertionError):assertion()


def test_executed_removed_quarantine_guard_is_detected(monkeypatch):
    old=source()
    def assertion():
        fresh=feed.refresh(old,email=EMAIL,anchors=old.associations,now=NOW,
            opener=Opener(payload([[9,'reused','AAA','NYSE'],[2,'other','BBB','NYSE']])))
        assert fresh.snapshot.resolve('AAA','NYSE','Common Stock','Common Stock',now=NOW).status=='UNRESOLVED'
    assertion()
    monkeypatch.setattr(feed,'quarantine_observation',lambda rows,anchors,blocked:(tuple(rows),tuple(anchors),()))
    with pytest.raises(AssertionError):assertion()


def test_native_final_submission_uses_current_quarantine_without_rewriting_old_plan_or_claim(conn,monkeypatch):
    previous=setup(conn,monkeypatch)
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(journal.WRITER_LOCK_KEY,))
    _state,plan,_projection,evidence=prepare(conn,previous,pending=('A','A2'))
    allowed=admission.check_buy(conn,evidence=evidence,security_id='A',reconciliation=reconciliation(),now=NOW,reserve=True)
    assert allowed.allowed
    assert not admission.check_buy(conn,evidence=evidence,security_id='A2',reconciliation=reconciliation(),now=NOW,reserve=True).allowed
    claims=admission._claims(conn,admission._binding(BINDING))
    assert len(claims)==1
    before=json.dumps({key:value.model_dump(mode='json') for key,value in claims.items()},sort_keys=True)
    conn.commit()
    assert worker.collect(conn,email=EMAIL,now=NOW,opener=Opener())['status']=='REFRESHED'
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(journal.WRITER_LOCK_KEY,))
    assert admission.final_command_check(conn,evidence=evidence,command=command('A',plan=plan.plan_id),
        reconciliation=reconciliation(),now=NOW).allowed
    conn.commit()
    later=NOW+timedelta(days=1)
    assert worker.collect(conn,email=EMAIL,now=later,opener=Opener(payload([
        [9,'reused','AAA','NYSE'],[2,'other','BBB','NYSE']])) )['status']=='REFRESHED'
    conn.execute('SELECT pg_advisory_xact_lock(%s)',(journal.WRITER_LOCK_KEY,))
    denied=admission.final_command_check(conn,evidence=evidence,command=command('A',plan=plan.plan_id),
        reconciliation=reconciliation(at=later),now=later)
    assert not denied.allowed and denied.reason=='ISSUER_RESERVED_IDENTITY_CHANGED'
    assert admission.load_plan_evidence(conn,plan=plan,projection=_projection)==evidence
    assert json.dumps({key:value.model_dump(mode='json') for key,value in admission._claims(conn,admission._binding(BINDING)).items()},sort_keys=True)==before


def test_expired_cache_failure_never_reauthorizes_old_plan_and_near_expiry_success_renews(conn,monkeypatch):
    previous=setup(conn,monkeypatch)
    now=NOW+timedelta(days=31)
    assert worker.collect(conn,email=EMAIL,now=now,opener=Opener(status=403))['status']=='UNAVAILABLE'
    assert worker.diagnostic(conn,binding=BINDING,now=now)['valid'] is False
    view=worker.eligibility(conn,binding=BINDING,original=previous,now=now)
    assert view.resolve('AAA','NYSE','Common Stock','Common Stock',now=now).status=='UNRESOLVED'
    assert worker.collect(conn,email=EMAIL,now=now+timedelta(hours=1),opener=Opener())['status']=='REFRESHED'
    assert worker.diagnostic(conn,binding=BINDING,now=now+timedelta(hours=1))['valid'] is True
    renewed=worker.current_snapshot(conn,binding=BINDING,fallback=previous,now=now+timedelta(hours=1))
    assert renewed.provenance.expires_at_utc>now and previous.provenance.expires_at_utc<now


def test_killed_attempt_keeps_durable_backoff_and_releases_only_its_refresh_lock(conn,monkeypatch):
    previous=setup(conn,monkeypatch)
    class Killed(BaseException):pass
    def die(request):raise Killed()
    with pytest.raises(Killed):worker.collect(conn,email=EMAIL,now=NOW,opener=Opener(callback=die))
    status,_catalog,retained=worker._load(conn,BINDING,previous)
    assert status.reason=='attempt_started' and retained==previous
    client=Opener()
    assert worker.collect(conn,email=EMAIL,now=NOW+timedelta(minutes=1),opener=client)['status']=='CACHED'
    assert not client.calls


@pytest.mark.parametrize('damage',['missing_catalog','body_digest','foreign_binding','future_clock'])
def test_native_corrupt_or_foreign_cache_refuses_before_http(conn,monkeypatch,damage):
    previous=setup(conn,monkeypatch)
    worker.collect(conn,email=EMAIL,now=NOW,opener=Opener())
    key=worker._key('anchors' if damage=='missing_catalog' else 'current',BINDING)
    if damage=='missing_catalog':conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s',(key,))
    else:
        record=conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',(key,)).fetchone()[0]
        if damage=='body_digest':record['body']['reason']='forged'
        elif damage=='foreign_binding':
            body=record['body'];body['binding']['takeover_epoch']+=1
            body['sha256']=reference._digest({k:v for k,v in body.items() if k!='sha256'})
        else:
            body=record['body'];body['attempted_at']=(NOW+timedelta(hours=1)).isoformat()
            body['next_attempt_at']=(NOW+timedelta(days=2)).isoformat()
            body['sha256']=reference._digest({k:v for k,v in body.items() if k!='sha256'})
        record['sha256']=reference._digest({'kind':record['kind'],'body':record['body']})
        conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',(json.dumps(record),key))
    conn.commit();client=Opener()
    with pytest.raises(ValueError):worker.collect(conn,email=EMAIL,now=NOW+timedelta(minutes=1),opener=client)
    assert not client.calls


def test_session_refresh_lock_prevents_competing_provider_owner(conn,monkeypatch):
    setup(conn,monkeypatch)
    from sentinel.feed import store
    other=store.connect(conn.info.dsn)
    try:
        other.execute('SELECT pg_advisory_lock(%s)',(worker.REFRESH_LOCK,));other.commit()
        client=Opener()
        assert worker.collect(conn,email=EMAIL,now=NOW,opener=client)['status']=='DEFERRED'
        assert not client.calls
    finally:other.close()


def test_diagnostic_and_buy_identity_read_cached_facts_in_server_readonly_transaction(conn,monkeypatch):
    previous=setup(conn,monkeypatch)
    worker.collect(conn,email=EMAIL,now=NOW,opener=Opener())
    monkeypatch.setattr(feed,'refresh',lambda *a,**kw:pytest.fail('reader made provider call'))
    conn.execute('SET TRANSACTION READ ONLY')
    assert worker.diagnostic(conn,binding=BINDING,now=NOW)['valid'] is True
    assert worker.eligibility(conn,binding=BINDING,original=previous,now=NOW).resolve(
        'AAA','NYSE','Common Stock','Common Stock',now=NOW).issuer_id=='SEC_CIK:0000000001'
    assert conn.execute('SHOW transaction_read_only').fetchone()[0]=='on'


def test_opening_window_is_persisted_and_never_fetches_until_native_boundary(conn,monkeypatch):
    previous=setup(conn,monkeypatch)
    monkeypatch.setattr(worker,'_opening_delay',lambda now:600)
    client=Opener()
    assert worker.collect(conn,email=EMAIL,now=NOW,opener=client)['status']=='DEFERRED'
    current,_catalog,retained=worker._load(conn,BINDING,previous)
    assert current.reason=='deferred_opening_window' and current.next_attempt_at==NOW+timedelta(seconds=600)
    assert retained==previous and not client.calls


def test_literal_contact_is_only_passed_to_the_independent_collector():
    from pathlib import Path
    import os,yaml
    root=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
    services=yaml.safe_load((root/'docker-compose.sentinel-automation.yml').read_text())['services']
    receivers=[name for name,service in services.items() if feed.CONTACT_ENV in service.get('environment',{})]
    assert receivers==['sentinel-execution-collector']
    assert feed.CONTACT_ENV+'=' in (root/'.env.example').read_text()


def test_executed_removed_contact_guard_is_detected_before_provider_access(monkeypatch):
    previous=source();client=Opener()
    def assertion():
        with pytest.raises(ValueError):feed.refresh(previous,email='invalid',anchors=previous.associations,now=NOW,opener=client)
    assertion();assert not client.calls
    monkeypatch.setattr(feed,'declared_user_agent',lambda value:value)
    with pytest.raises(pytest.fail.Exception,match='DID NOT RAISE'):assertion()


def test_collector_keeps_account_fill_priority_and_issuer_deadline_and_failure_isolation(monkeypatch,tmp_path):
    from threading import Event
    from sentinel import execution_collector as collector,local_paper
    from sentinel.execution import fill_notifications
    monkeypatch.setattr(collector,'HEARTBEAT',tmp_path/'heartbeat')
    monkeypatch.setattr(collector.signal,'signal',lambda *args:None)
    monkeypatch.setattr(local_paper,'enabled',lambda:True)
    monkeypatch.setenv(fill_notifications.SINCE_ENV,'2026-10-26T00:00:00Z')
    monkeypatch.setenv(feed.CONTACT_ENV,EMAIL)
    monkeypatch.delenv('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY',raising=False)
    stop=Event();calls=[];messages=[]
    def runner(operation,*args,**kwargs):
        calls.append((operation,args,kwargs))
        if args==('ISSUER',):
            stop.set();raise TimeoutError('private response '+EMAIL)
    monkeypatch.setattr(collector.supervisor_io,'report',messages.append)
    assert collector.run(stopped=stop,runner=runner)==0
    assert [args[0] for operation,args,_ in calls]==['ACCOUNT','FILL','ISSUER']
    assert calls[-1][2]=={'timeout':15,'start_method':'spawn'}
    assert all(operation is collector.collect_once for operation,_,_ in calls)
    assert messages==['execution collector unavailable: TimeoutError']
