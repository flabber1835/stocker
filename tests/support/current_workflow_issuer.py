"""Generated issuer inputs and genuine read-only enrollment for private PAPER.

No production reference file, issuer validator or broker guard is replaced.
The temporary file and expected digest are external fixture inputs, like the
private signing root. Generated associations do not claim actual SEC coverage.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

from sentinel import binding, rolling_checkpoint
from sentinel.automation import store
from sentinel.execution import issuer_admission, journal
from sentinel.execution.guarded import PaperPreparationGrant
from sentinel.feed import issuer_reference
from sentinel.feed.rolling_contract import canonical_json, digest
from sentinel.paper import issuer_enrollment, validation
from sentinel.strategy import production_strategy


def install_generated_reference(instruments, *, now, monkeypatch, tmp_path):
    """Retain exact generated listings; the real parser authenticates the file."""
    selected=sorted(instruments.values(),key=lambda item:item.symbol)
    assert selected and len({item.symbol for item in selected})==len(selected)
    assert all(item.exchange=='NASDAQ' and item.security_type=='Common Stock'
               and item.security_type2=='Common Stock' for item in selected)
    source=issuer_reference.IssuerReferenceSnapshot.create(
        observed_at_utc=now-timedelta(minutes=1),
        associations=[dict(cik=f'{1000000000+index:010d}',ticker=item.symbol,exchange='Nasdaq')
                      for index,item in enumerate(selected)],
        capture_sha256=digest({'kind':'GENERATED_CURRENT_WORKFLOW_ISSUERS',
            'instruments':[item.model_dump(mode='json') for item in selected]}))
    path=tmp_path/'generated-current-issuer-reference.json'
    path.write_text(canonical_json(source.model_dump(mode='json')),encoding='utf-8')
    monkeypatch.setattr(issuer_reference,'BUNDLED_PATH',path)
    monkeypatch.setattr(issuer_reference,'BUNDLED_SNAPSHOT_SHA256',source.sha256)
    assert issuer_reference.load_snapshot()==source
    return source


def enroll_generated_account(conn, *, campaign, clock, observation_id):
    """Use the real signed, sealed GET-only operation before worker activation."""
    assert conn.info.dbname.startswith('operational_')
    owner=binding.require(conn)
    assert owner.broker_account_id=='PAISOLATEDWORKFLOW'
    before=rolling_checkpoint.read(conn).model_dump(by_alias=True)
    control=store.load_control(conn)
    assert not control.enabled and control.kill_switch_engaged
    assert not journal.load_commands(conn,owner.identity)
    grant=PaperPreparationGrant(owner.broker_account_id,date.fromisoformat(before['session']))
    broker=validation._guard_broker(conn=conn,
        broker=campaign._broker(conn,before['session']),grant=grant,
        base_url=campaign.sentinel_config.base_url,now_provider=clock.now,
        strategy_provider=lambda:production_strategy()[1],
        automation_config_sha256=campaign.automation_config.fingerprint,
        dual_shadow_observation_id=observation_id,dual_shadow_starting_cash=Decimal('50000'))
    conn.rollback()
    enrolled=asyncio.run(issuer_enrollment.enroll_current_paper_account(
        conn=conn,broker=broker,base_url=campaign.sentinel_config.base_url,
        shadow_observation_id=observation_id,shadow_starting_cash=Decimal('50000'),now=clock.now()))
    assert enrolled==issuer_admission.load_enrollment(conn,binding=owner.identity)
    assert not enrolled.episodes and enrolled.native_positions=={}
    assert rolling_checkpoint.read(conn).model_dump(by_alias=True)==before
    assert store.load_control(conn)==control
    assert not journal.load_commands(conn,owner.identity)
    conn.rollback()
    return enrolled
