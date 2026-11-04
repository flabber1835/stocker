"""Pure delivery-observer comparison of an advanced canonical backup checkpoint."""
from __future__ import annotations

from datetime import datetime, timedelta
import re


class BackupReadinessRefused(RuntimeError):
    """The supplied trusted observations do not establish current readiness."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise BackupReadinessRefused(reason)


def _clock(value: str) -> datetime:
    _require(isinstance(value, str), 'missing clock')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _require(result.utcoffset() == timedelta(0), 'clock must be UTC')
    return result


def current_checkpoint_advancement(
    snapshot: dict, tick: dict, now: datetime, *, expected_commit: str,
    expected_image_digest: str, expected_account: str, expected_engine: str,
) -> dict:
    """Compare already authenticated observations; never grant mutation authority.

    The caller owns canonical authentication, native invocation/age/owner checks,
    and fresh primary/account observations. This function performs no IO.
    """
    _require(isinstance(snapshot,dict),'current runtime checkpoint observation missing')
    _require(snapshot.get('checkpoint_authenticated') is True
            and snapshot.get('native_chain_authenticated') is True
            and snapshot.get('capacity_valid') is True,'current chain evidence unauthenticated')
    _require(timedelta(0)<=now-_clock(snapshot.get('observed_at'))<=timedelta(seconds=5),
            'current checkpoint observation stale or future')
    primary=snapshot['primary'];checkpoint=snapshot['checkpoint'];context=snapshot['current_context']
    _require(checkpoint.get('context')==context and context.get('system_identifier')==primary.get('system_identifier')
            and context.get('postmaster_start_us')==primary.get('postmaster_start_us')
            and context.get('git_commit')==expected_commit and context.get('runtime_image_digest')==expected_image_digest
            and context.get('broker')=='alpaca' and context.get('broker_account_id')==expected_account
            and primary.get('archive_mode')=='on','current checkpoint runtime/account context changed')
    _require(snapshot.get('capacity_engine')==expected_engine
            and checkpoint.get('engine_id')==snapshot['capacity_engine'],'current checkpoint engine changed')
    native=snapshot['native_chain'];chain=checkpoint['chain'];size=snapshot['segment_size']
    _require(type(size) is int and 1024**2<=size<=1024**3 and size&(size-1)==0,'checkpoint WAL geometry invalid')
    per_log=2**32//size
    def index(value):
        _require(isinstance(value,str) and re.fullmatch('[0-9A-F]{24}',value) is not None,'checkpoint WAL name invalid')
        segment=int(value[16:],16)
        _require(segment<per_log,'checkpoint WAL segment invalid')
        return int(value[8:16],16)*per_log+segment
    for producer,value in (('native',native),('checkpoint',chain)):
        _require(isinstance(value,dict) and value.get('enabled') is True
                and value.get('backup_state')!='DEGRADED'
                and value.get('system_identifier')==primary['system_identifier']
                and value.get('base_backup')==tick.get('base')
                and value.get('wal_integrity')=='sha256-sidecar-v1','current chain integrity/base changed')
        start,marker,end=[value.get(k) for k in ('recoverable_from_wal','recovery_marker_wal','recoverable_through_wal')]
        first,middle,last=map(index,(start,marker,end))
        _require(start[:8]==marker[:8]==end[:8] and first<=middle<=last
                and type(value.get('wal_segments')) is int and value['wal_segments']==last-first+1
                and 1<=value['wal_segments']<=1024,
                'current verified chain interval invalid')
        objects=value['wal_segments']+(value.get('timeline_history') is not None)
        hashed=value.get('integrity_objects_hashed');passes=value.get('integrity_read_passes')
        full=value.get('integrity_full_scrub')
        native_shape=(full is True and type(passes) is int and passes==1
                      and type(hashed) is int and hashed==objects
                      and 'integrity_max_reuse_seconds' not in value)
        runtime_shape=(producer=='checkpoint' and type(full) is bool
                       and type(value.get('integrity_max_reuse_seconds')) is int
                       and value['integrity_max_reuse_seconds']==300
                       and type(hashed) is int and 0<=hashed<=2*objects and hashed%2==0
                       and type(passes) is int and passes==(2 if hashed else 0)
                       and (not full or hashed==2*objects))
        _require(native_shape or runtime_shape,'current producer integrity mode invalid')
    old,new=native['recoverable_through_wal'],chain['recoverable_through_wal']
    _require(old[:8]==new[:8] and index(old)<index(new)
            and native['recoverable_from_wal']==chain['recoverable_from_wal']
            and native['recovery_marker_wal']==chain['recovery_marker_wal']
            and native.get('timeline_history')==chain.get('timeline_history'),'checkpoint did not genuinely advance verified prefix')
    _require(new==primary.get('last_archived_wal')
            and checkpoint.get('last_archive_at')==primary.get('last_archive_at'),
            'checkpoint does not cover actual current archive boundary')
    _require(type(checkpoint.get('last_archive_at')) is int
            and 0<=primary['now']-checkpoint['last_archive_at']<600,
            'current checkpoint archive clock invalid')
    _require(timedelta(0)<=_clock(snapshot['journal_at'])-_clock(snapshot['native_chain_observed_at'])<=timedelta(seconds=60),
            'native verified scan does not match current tick')
    return {'source':'CURRENT_AUTHENTICATED_RUNTIME_CHECKPOINT','maintenance_checkpoint_refreshed':False,
            'native_verified_through_wal':old,'current_verified_through_wal':new,
            'original_last_archive_at':checkpoint['last_archive_at'],'observation':snapshot}
