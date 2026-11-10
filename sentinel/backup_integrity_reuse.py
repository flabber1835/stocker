"""Authenticated PAPER byte-proof reuse; every admission still checks media.

This is not restore qualification, continuity or financial authority. The
PostgreSQL host owns both the receipt and its boot/uptime clock. No inherited
Python dictionary or client wall clock grants cross-process reuse.
"""
from contextlib import contextmanager
from datetime import datetime
from functools import cache
import base64
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import shlex
import sys
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NAME = 'sentinel-backup-integrity-v1.json'
PURPOSE = 'sentinel.backup-integrity-reuse/1'
LOCK_KEY = 0x534E54424B503031
MAX_BYTES = 512 * 1024
MAX_AGE = 300


class Proof(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)
    schema_version: Literal['sentinel.backup-integrity-reuse/1']
    outcome: Literal['VALID', 'INVALID'] = 'VALID'
    context: dict[str, str | int]
    boot: str = Field(pattern=r'^[0-9a-f-]{36}$')
    completed_uptime: float = Field(ge=0)
    end: str = Field(pattern=r'^[0-9A-F]{24}$')
    metadata: dict[str, tuple[int | None, datetime | None, datetime | None,
                              str | None, datetime | None, datetime | None]]


def selected():
    from sentinel import local_paper
    from sentinel.config import DEFAULT_BASE_URL, trading_endpoint
    from sentinel.trading_environment import TradingEnvironment
    return (sys.platform == 'linux'
        and trading_endpoint(os.environ.get('ALPACA_BASE_URL', DEFAULT_BASE_URL)).environment
            is TradingEnvironment.PAPER
        and local_paper.enabled() and local_paper.backup_policy() == local_paper.BACKUP_POLICY
        and len(os.environ.get('SENTINEL_PUBLICATION_RECEIPT_KEY', '')) >= 32)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _signature(value):
    return hmac.new(os.environ['SENTINEL_PUBLICATION_RECEIPT_KEY'].encode(),
                    PURPOSE.encode()+b'\0'+_canonical(value), hashlib.sha256).hexdigest()


@cache
def implementation():
    files = (Path(__file__), Path(__file__).with_name('backup_runtime_authority.py'))
    return hashlib.sha256(b''.join(hashlib.sha256(p.read_bytes()).digest() for p in files)).hexdigest()


def _clock(conn):
    before = time.monotonic()
    row = conn.execute("SELECT pg_postmaster_start_time(),current_database(),"
        "pg_read_file('/proc/sys/kernel/random/boot_id',0,128),"
        "pg_read_file('/proc/uptime',0,128)").fetchone()
    try:
        start, database, boot, uptime = row
        boot = boot.strip(); uptime = float(uptime.split()[0])
        if (start.utcoffset() is None or not database or len(boot) != 36
                or not math.isfinite(uptime) or uptime < 0):
            raise ValueError('invalid server clock')
    except (TypeError, ValueError, AttributeError):
        raise ValueError('backup integrity server identity/clock unavailable') from None
    return {'postmaster': start.isoformat(), 'database': database}, boot, uptime, before


def _publish_sql(raw):
    encoded = base64.b64encode(raw).decode('ascii')
    script = f'''set -eu
target={NAME}
[ ! -L "$target" ]
if [ -e "$target" ]; then [ -f "$target" ] && [ "$(stat -c %h "$target")" = 1 ]; fi
temporary=$(mktemp "./.$target.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
chmod 0600 "$temporary"
IFS= read -r payload
printf '%s' "$payload" | base64 -d > "$temporary"
sync "$temporary"
mv -Tf -- "$temporary" "$target"
sync .'''
    program = ('sh -ceu '+shlex.quote(script)).replace("'", "''")
    return f"COPY (SELECT '{encoded}') TO PROGRAM '{program}'"


class Owner:
    def __init__(self, conn, context):
        self.conn = conn
        physical, self.boot, self.uptime, self.client_before = _clock(conn)
        self.context = dict(context, **physical, implementation=implementation())
        self.proof = None
        self.expired_window = None  # Diagnostic clocks only; never reusable proof.
        row = conn.execute('SELECT pg_read_binary_file(%s,0,%s,true)', (NAME, MAX_BYTES+1)).fetchone()
        if row is not None and row[0] is not None:
            raw = bytes(row[0])
            if not 0 < len(raw) <= MAX_BYTES:
                raise ValueError('backup integrity receipt exceeds bound')
            envelope = json.loads(raw)
            if (not isinstance(envelope, dict) or set(envelope) != {'proof','signature'}
                    or not isinstance(envelope['signature'], str)
                    or not hmac.compare_digest(envelope['signature'], _signature(envelope['proof']))):
                raise ValueError('backup integrity receipt authentication failed')
            proof = Proof.model_validate(envelope['proof'])
            if proof.outcome == 'VALID' and proof.context == self.context and proof.boot == self.boot:
                if 0 <= self.uptime-proof.completed_uptime < MAX_AGE:
                    self.proof = proof
                elif self.uptime-proof.completed_uptime >= MAX_AGE:
                    self.expired_window = (proof.completed_uptime, self.uptime)

    def cached(self):
        if self.proof is None:
            return None
        age = self.uptime-self.proof.completed_uptime
        return {'full_scrub_at': self.client_before-age,
                'objects': tuple(self.proof.metadata), 'metadata': self.proof.metadata,
                'end': self.proof.end}

    def publish(self, cached, *, full_scrub):
        from sentinel.backup_runtime_authority import (
            BackupRuntimeRefused, BackupRuntimeUnavailable, BackupIntegrityProofExpired)
        physical, boot, uptime, _ = _clock(self.conn)
        if (boot != self.boot or any(self.context[k] != v for k,v in physical.items())
                or uptime < self.uptime):
            raise BackupRuntimeRefused('backup integrity physical clock changed during proof')
        stamp = uptime if full_scrub else self.proof.completed_uptime
        if not 0 <= uptime-stamp < MAX_AGE:
            if uptime-stamp >= MAX_AGE:
                raise BackupIntegrityProofExpired(completed_uptime=stamp, observed_uptime=uptime)
            raise BackupRuntimeUnavailable('backup integrity complete proof expired during admission')
        proof = Proof(schema_version=PURPOSE, context=self.context, boot=boot,
                      completed_uptime=stamp, end=cached['end'], metadata=cached['metadata'])
        if self.proof == proof:
            return  # Metadata-only admission is not another durable write.
        body = proof.model_dump(mode='json')
        raw = _canonical({'proof':body, 'signature':_signature(body)})
        if len(raw) > MAX_BYTES:
            raise ValueError('backup integrity receipt exceeds bound')
        self.conn.execute(_publish_sql(raw))

    def invalidate(self):
        """An observed failed proof cannot leave a reusable positive receipt."""
        proof = Proof(schema_version=PURPOSE, outcome='INVALID', context=self.context,
            boot=self.boot, completed_uptime=self.uptime, end='0'*24, metadata={})
        body = proof.model_dump(mode='json')
        self.conn.execute(_publish_sql(_canonical({'proof':body,'signature':_signature(body)})))


@contextmanager
def owner(conn, *, system_id, base, start, segment_size):
    if not selected():
        yield None
        return
    from sentinel.backup_runtime_authority import BackupIntegrityBusy, BackupRuntimeRefused
    from psycopg.pq import TransactionStatus
    if conn.info.transaction_status not in {TransactionStatus.INTRANS, TransactionStatus.IDLE}:
        raise BackupRuntimeRefused('backup integrity reuse requires a usable admission transaction')
    acquired = False
    value = None
    try:
        # A borrowed transaction uses a savepoint. An autocommit CLI starts
        # only this proof transaction; no borrowed financial work is committed.
        with conn.transaction():
            acquired = conn.execute('SELECT pg_try_advisory_lock(%s)', (LOCK_KEY,)).fetchone() == (True,)
            if not acquired:
                raise BackupIntegrityBusy('another backup integrity proof owner is active')
            try:
                value = Owner(conn, {'system_id':system_id, 'base':base,
                                     'start':start, 'segment_size':segment_size})
            except (ValueError, KeyError, TypeError) as exc:
                raise BackupRuntimeRefused('backup integrity reuse record or clock is invalid') from exc
            yield value
    except BaseException:
        # The proof savepoint has rolled back first, so an aborted media read
        # cannot prevent this primary-local invalidation or commit caller work.
        if acquired and value is not None:
            with conn.transaction():
                value.invalidate()
        raise
    finally:
        if acquired:
            with conn.transaction():
                if conn.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,)).fetchone() != (True,):
                    raise BackupRuntimeRefused('backup integrity proof ownership lost')
