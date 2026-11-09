"""Finite, fair disposal with durable progress; failures only retain data."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import logging
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel.feed import rolling_jobs, rolling_store, store
from sentinel.feed.rolling_contract import canonical_json

log = logging.getLogger(__name__)
BATCH_ROWS = rolling_store.BATCH_SIZE
ACQUISITION_BATCH_ROWS = 128
PROBE_SECONDS = 1.0
PASS_SECONDS = 5.0
HINT_SECONDS = .1
CLASS_SECONDS = .5
CHECKPOINT_RESERVE = .2
PAGE_QUANTUM = 64
ROW_QUANTUM = 5000
MAX_LEGACY_EXTENTS = 64
EXTENT_RETURN_RESERVE = .025
PAYLOAD_TABLES = {'BARS':'sentinel_snapshot_bars', 'BENCHMARKS':'sentinel_snapshot_benchmarks'}


class RetentionProgressRefused(ValueError):
    pass


class RetentionBudgetExpired(TimeoutError):
    pass


class _ProgressModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True,
                              populate_by_name=True, allow_inf_nan=False)


class PhysicalCursor(_ProgressModel):
    phase: Literal['BARS','BENCHMARKS']
    relation_oid: int = Field(gt=0)
    relation_filenode: int = Field(gt=0)
    upper_block: int = Field(ge=0, le=4294967295)
    position_block: int = Field(default=0, ge=0, le=4294967295)
    position_offset: int = Field(default=0, ge=0, le=65535)
    page_quantum: Literal[1,2,4,8,16,32,64] = PAGE_QUANTUM

    @model_validator(mode='after')
    def location(self):
        if self.position_block > self.upper_block or (self.position_block == self.upper_block
                                                      and self.position_offset):
            raise ValueError('physical retention position exceeds its fixed boundary')
        return self


class CandidateCursor(_ProgressModel):
    candidate_id: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    phase: Literal['BARS','BENCHMARKS'] = 'BARS'
    last_session: str | None = None
    last_security_id: str | None = Field(default=None, min_length=1, max_length=256)
    row_quantum: int = Field(default=ROW_QUANTUM, ge=1, le=ROW_QUANTUM)

    @field_validator('last_session')
    @classmethod
    def iso_session(cls, value):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError('retention session is not canonical')
        return value

    @model_validator(mode='after')
    def key(self):
        if ((self.phase == 'BENCHMARKS' and self.last_security_id is not None)
                or (self.phase == 'BARS' and ((self.last_session is None)
                                            != (self.last_security_id is None)))):
            raise ValueError('retention logical key is incomplete')
        return self


class RetentionProgress(_ProgressModel):
    schema_version: Literal['sentinel.retention-progress/1'] = Field(
        default='sentinel.retention-progress/1', alias='schema')
    known_retirement_count: int = Field(ge=0)
    metadata_cursor: str | None = Field(default=None,
        pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    next_class: int = Field(default=0, ge=0, le=6)
    legacy: PhysicalCursor | None = None
    active: CandidateCursor | None = None

    @model_validator(mode='after')
    def queue(self):
        if self.legacy is not None and self.active is not None:
            raise ValueError('legacy bootstrap and new retirement queue cannot overlap')
        return self


class _Budget:
    """Caller-owned transaction with finite query admission, never a new owner."""
    def __init__(self, raw, deadline, *, ceiling_ms=5000, authorization=None,
                 parent=None):
        self.raw, self.deadline, self.ceiling_ms = raw, deadline, ceiling_ms
        self.authorization = authorization
        self.parent = parent

    def check(self):
        if time.monotonic() >= self.deadline:
            raise RetentionBudgetExpired('retention work quantum exhausted')

    def _prepare(self):
        self.check()
        remaining = max(1, min(self.ceiling_ms, int((self.deadline-time.monotonic())*1000)))
        self.raw.execute(f"SET LOCAL statement_timeout='{remaining}ms'")
        self.check()

    def execute(self, query, params=None):
        self._prepare()
        return self.raw.execute(query, params)

    def authorize(self):
        guard = self.authorization or _Authorization(self.raw,time.monotonic()+PASS_SECONDS)
        first_attempt = not guard.complete and guard.error is None
        try:
            guard.require()
        finally:
            # Full checkpoint authentication has its original remaining pass
            # budget. Failed proof grants no mutation, but must not discard
            # earlier empty extents merely for consuming its separate budget.
            if first_attempt:
                owner = self.parent or self
                owner.deadline = min(guard.deadline,time.monotonic()+CLASS_SECONDS)
                self.deadline = (owner.deadline-EXTENT_RETURN_RESERVE
                                 if self.parent else owner.deadline)
        self.check()

    def cursor(self, *args, **kwargs):
        owner, cursor = self, self.raw.cursor(*args, **kwargs)
        class Cursor:
            def __enter__(self):
                cursor.__enter__()
                return self
            def __exit__(self, *values):
                return cursor.__exit__(*values)
            def execute(self, query, params=None):
                owner._prepare()
                cursor.execute(query, params)
                return self
            def __getattr__(self, name):
                return getattr(cursor, name)
        return Cursor()

    def __getattr__(self, name):
        return getattr(self.raw, name)


def _authenticate_checkpoints(conn):
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    if conn.execute("SELECT to_regclass('sentinel_processed_sessions')").fetchone()[0]:
        rolling_checkpoint.read(conn)
        rolling_daily_checkpoint.read(conn)


class _Authorization:
    """Only this owned transaction may reuse its original full checkpoint read."""
    def __init__(self, conn, deadline):
        self.conn, self.deadline = conn, deadline
        self.complete = False
        self.error = None

    def require(self):
        if self.error is not None:
            raise self.error
        if self.complete:
            return False
        port = _Budget(self.conn,self.deadline)
        try:
            _authenticate_checkpoints(port)
            port.check()
        except Exception as exc:
            self.error = exc
            raise
        self.complete = True
        return True


def _authorize(conn):
    if isinstance(conn,_Budget):
        conn.authorize()
    else:
        # Direct private helper calls still get the original guard. Production
        # dispatch supplies the one transaction-owned authorization object.
        _Authorization(conn,time.monotonic()+PASS_SECONDS).require()


@contextmanager
def _pin_planning(conn):
    """Suppress proved repeated compilation, keeping canonical pin authority."""
    raw = conn.raw if isinstance(conn,_Budget) else conn
    raw.execute('SAVEPOINT retention_pin_planning')
    try:
        previous = conn.execute("WITH prior AS MATERIALIZED (SELECT current_setting('jit') AS jit) "
            "SELECT jit,CASE WHEN jit='on' THEN set_config('jit','off',true) ELSE jit END FROM prior"
            ).fetchone()[0]
        if previous not in {'on','off'}:
            raise RetentionProgressRefused('unknown acquisition pin compilation setting')
        yield
        if previous=='on':
            conn.execute("SELECT set_config('jit',%s,true)",(previous,))
    except BaseException:
        # Cancellation can leave the transaction aborted. Restore by rollback,
        # never an attempted SET which might replace the original exception.
        try:
            raw.execute('ROLLBACK TO SAVEPOINT retention_pin_planning')
            raw.execute('RELEASE SAVEPOINT retention_pin_planning')
        except Exception:
            pass
        raise
    else:
        raw.execute('RELEASE SAVEPOINT retention_pin_planning')


def _read_progress(conn):
    row = conn.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance WHERE id').fetchone()
    if row is None:
        return None
    if not isinstance(row[0], dict):
        raise RetentionProgressRefused('maintenance diagnostic is not an object')
    if 'progress' not in row[0]:
        return None
    try:
        return RetentionProgress.model_validate(row[0]['progress'])
    except ValueError as exc:
        raise RetentionProgressRefused('maintenance progress is malformed') from exc


def _retirement_count(conn):
    return int(conn.execute('SELECT count(*) FROM sentinel_snapshot_retirements').fetchone()[0])


def _physical_cursor(conn, phase, *, quantum=PAGE_QUANTUM, require_access=False):
    table = PAYLOAD_TABLES[phase]
    # Hold the identity before sampling it; a metadata function's temporary
    # relation access alone must not leave a rewrite gap before the first scan.
    conn.execute(f'LOCK TABLE {table} IN ACCESS SHARE MODE')
    row = conn.execute('SELECT c.oid,pg_relation_filenode(c.oid),'
        'pg_relation_size(c.oid)/current_setting(\'block_size\')::bigint, '
        "current_setting('server_version_num')::int,current_setting('enable_tidscan') "
        "FROM pg_class c WHERE c.oid=%s::regclass AND c.relkind='r' AND c.relpersistence='p' "
        "AND c.relam=(SELECT oid FROM pg_am WHERE amname='heap')",
        (table,)).fetchone()
    if row is None or row[1] is None:
        raise RetentionProgressRefused('retention payload is not a supported logged heap')
    if require_access and (not 160000<=row[3]<170000 or row[4]!='on'):
        raise RetentionProgressRefused('physical retention requires qualified PG16 TID access')
    return PhysicalCursor(phase=phase, relation_oid=row[0], relation_filenode=row[1],
                          upper_block=row[2], page_quantum=quantum)


def _initial_progress(conn):
    row = conn.execute('SELECT diagnostic FROM sentinel_snapshot_maintenance WHERE id').fetchone()
    old = row[0] if row is not None else {}
    if not isinstance(old, dict):
        raise RetentionProgressRefused('maintenance diagnostic is not an object')
    count = _retirement_count(conn)
    return RetentionProgress(known_retirement_count=count,
        metadata_cursor=old.get('scan_cursor'),
        legacy=_physical_cursor(conn,'BARS') if count else None)


def _write_result(conn, result, progress):
    payload = dict(result, progress=progress.model_dump(by_alias=True),
                   scan_cursor=progress.metadata_cursor)
    conn.execute('INSERT INTO sentinel_snapshot_maintenance(id,diagnostic) VALUES(TRUE,%s::jsonb) '
        'ON CONFLICT(id) DO UPDATE SET updated_at=clock_timestamp(),diagnostic=EXCLUDED.diagnostic',
        (canonical_json(payload),))


def _stats(**changes):
    result = dict(candidate_id=None, deleted_rows=0, released_evidence=0,
        deleted_scratch_rows=0, retired_candidate_id=None, retired_count=0,
        retained={}, retained_count=0, deleted_acquisition_rows=0,
        deleted_acquisition_parts=0, released_normalized_blocks=0,
        traversed_blocks=0, progress_made=False, metadata_more=False)
    result.update(changes)
    return result


def _physical_select_sql(table):
    if table not in PAYLOAD_TABLES.values():
        raise ValueError('unsupported retention payload table')
    return (f'WITH physical AS MATERIALIZED (SELECT ctid,candidate_id FROM {table} '
        'WHERE ctid>%s::tid AND ctid<%s::tid) '
        'SELECT p.ctid FROM physical p JOIN sentinel_snapshot_retirements r USING(candidate_id) '
        'ORDER BY p.ctid LIMIT %s')


def _physical_delete_sql(table):
    if table not in PAYLOAD_TABLES.values():
        raise ValueError('unsupported retention payload table')
    return (f'WITH deleted AS (DELETE FROM {table} WHERE ctid>%s::tid AND ctid<%s::tid '
        'AND ctid=ANY(%s::tid[]) RETURNING ctid) SELECT count(*),max(ctid) FROM deleted')


def _bootstrap_step(conn, progress, *, batch_rows, _witnesses=None):
    cursor = progress.legacy
    if cursor is None:
        return progress, _stats()
    witnesses = {} if _witnesses is None else _witnesses
    def observe(phase):
        if phase not in witnesses:
            witnesses[phase] = _physical_cursor(conn,phase,quantum=cursor.page_quantum,
                                                require_access=True)
        return witnesses[phase]
    observed = observe(cursor.phase)
    if (observed.relation_oid, observed.relation_filenode) != (
            cursor.relation_oid,cursor.relation_filenode):
        return progress.model_copy(update={'legacy':observed}), _stats(progress_made=True)
    if cursor.position_block >= cursor.upper_block:
        next_cursor = (observe('BENCHMARKS') if cursor.phase=='BARS' else None)
        if next_cursor is not None and next_cursor.upper_block == 0:
            next_cursor = None
        return progress.model_copy(update={'legacy':next_cursor}), _stats(progress_made=True)
    upper = min(cursor.upper_block,cursor.position_block+cursor.page_quantum)
    lower = f'({cursor.position_block},{cursor.position_offset})'
    end = f'({upper},0)'
    table = PAYLOAD_TABLES[cursor.phase]
    limit = min(batch_rows,ROW_QUANTUM)
    selected = conn.execute(_physical_select_sql(table),(lower,end,limit+1)).fetchall()
    tids = [str(row[0]) for row in selected[:limit]]
    count,last = 0,None
    if tids:
        _authorize(conn)
        count,last = conn.execute(_physical_delete_sql(table),(lower,end,tids)).fetchone()
        if count != len(tids):
            raise RetentionProgressRefused('physical disposal changed during its locked pass')
    if len(selected)>limit:
        if last is None:
            raise RetentionProgressRefused('full physical batch has no last position')
        block,offset = (int(value) for value in str(last).strip('()').split(','))
    else:
        block,offset = upper,0
    after = cursor.model_copy(update={'position_block':block,'position_offset':offset})
    if block >= cursor.upper_block:
        after = observe('BENCHMARKS') if cursor.phase=='BARS' else None
        if after is not None and after.upper_block == 0:
            after = None
    return progress.model_copy(update={'legacy':after}), _stats(deleted_rows=count,
        traversed_blocks=block-cursor.position_block,progress_made=True)


def _bootstrap_class(conn, progress, *, batch_rows):
    """Spend one class slice on finite extents without losing completed work."""
    raw = conn.raw if isinstance(conn,_Budget) else conn
    total, witnesses = _stats(), {}
    for _ in range(MAX_LEGACY_EXTENTS):
        remaining = batch_rows-total['deleted_rows']
        if progress.legacy is None or remaining<=0:
            break
        if isinstance(conn,_Budget):
            if time.monotonic()>=conn.deadline-EXTENT_RETURN_RESERVE:
                break
            extent = _Budget(raw,conn.deadline-EXTENT_RETURN_RESERVE,ceiling_ms=500,
                             authorization=conn.authorization,parent=conn)
        else:
            extent = conn
        raw.execute('SAVEPOINT retention_extent')
        try:
            after, changes = _bootstrap_step(extent,progress,batch_rows=remaining,
                                             _witnesses=witnesses)
            if isinstance(extent,_Budget):
                extent.check()
        except Exception as exc:
            raw.execute('ROLLBACK TO SAVEPOINT retention_extent')
            guard = conn.authorization if isinstance(conn,_Budget) else None
            if (exc is not getattr(guard,'error',None)
                    and (isinstance(exc,RetentionBudgetExpired)
                         or getattr(exc,'sqlstate',None)=='57014')):
                progress = _smaller_payload(progress)
            total['retry_reason'] = type(exc).__name__
            break
        else:
            progress = after
            _merge_stats(total,changes)
        finally:
            raw.execute('RELEASE SAVEPOINT retention_extent')
    return progress,total


def _logical_step(conn, progress, *, batch_rows):
    cursor = progress.active
    if cursor is None:
        return progress, _stats()
    table = PAYLOAD_TABLES[cursor.phase]
    if not conn.execute('SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=%s',
                        (cursor.candidate_id,)).fetchone():
        raise RetentionProgressRefused('active disposal candidate is not retired')
    columns = 'session,security_id' if cursor.phase=='BARS' else 'session'
    predicate, params = '', [cursor.candidate_id]
    if cursor.last_session is not None:
        if cursor.phase=='BARS':
            predicate = ' AND (session,security_id)>(%s::date,%s::text)'
            params.extend((cursor.last_session,cursor.last_security_id))
        else:
            predicate = ' AND session>%s::date'
            params.append(cursor.last_session)
    limit = min(batch_rows,cursor.row_quantum)
    selected = conn.execute(f'SELECT ctid,{columns} FROM {table} WHERE candidate_id=%s'
                        +predicate+f' ORDER BY {columns} LIMIT %s', (*params,limit+1)).fetchall()
    rows = selected[:limit]
    if not rows:
        after = (CandidateCursor(candidate_id=cursor.candidate_id,phase='BENCHMARKS',
                                 row_quantum=cursor.row_quantum) if cursor.phase=='BARS' else None)
        advanced = progress.model_copy(update={'active':after})
        if after is not None:
            advanced, changes = _logical_step(conn,advanced,batch_rows=limit)
            changes['progress_made'] = True
            return advanced, changes
        return advanced, _stats(progress_made=True)
    _authorize(conn)
    previous = conn.execute('WITH prior AS MATERIALIZED (SELECT '
        "current_setting('enable_seqscan') AS seq,current_setting('enable_tidscan') AS tid,"
        "current_setting('enable_indexscan') AS idx,current_setting('enable_bitmapscan') AS bitmap,"
        "current_setting('server_version_num')::int AS version) "
        "SELECT seq,tid,idx,bitmap,version,"
        "CASE WHEN idx='on' AND bitmap='on' AND version>=160000 AND version<170000 "
        "THEN set_config('enable_seqscan','off',true) ELSE seq END,"
        "CASE WHEN idx='on' AND bitmap='on' AND version>=160000 AND version<170000 "
        "THEN set_config('enable_tidscan','on',true) ELSE tid END FROM prior").fetchone()
    if (not 160000<=previous[4]<170000 or previous[2:4]!=('on','on')
            or any(value not in {'on','off'} for value in previous[:2])):
        raise RetentionProgressRefused('unsupported local planner configuration')
    result = conn.execute(f'DELETE FROM {table} WHERE candidate_id::text=%s::uuid::text '
                          'AND ctid=ANY(%s::tid[])',
                          (cursor.candidate_id,[str(row[0]) for row in rows]))
    deleted = result.rowcount
    # On failure the enclosing class SAVEPOINT restores GUCs; do not issue a
    # finally query which could mask the original cancellation.
    conn.execute("SELECT set_config('enable_seqscan',%s,true),set_config('enable_tidscan',%s,true)",
                 previous[:2])
    if deleted != len(rows):
        raise RetentionProgressRefused('logical disposal changed during its locked pass')
    last = rows[-1]
    after = cursor.model_copy(update={'last_session':str(last[1]),
        'last_security_id':last[2] if cursor.phase=='BARS' else None})
    if len(selected) <= limit:
        after = (CandidateCursor(candidate_id=cursor.candidate_id,phase='BENCHMARKS',
                                 row_quantum=cursor.row_quantum) if cursor.phase=='BARS' else None)
    advanced = progress.model_copy(update={'active':after})
    changes = _stats(candidate_id=cursor.candidate_id,deleted_rows=deleted,progress_made=True)
    if cursor.phase=='BARS' and after is not None and after.phase=='BENCHMARKS' and deleted<limit:
        advanced, following = _logical_step(conn,advanced,batch_rows=limit-deleted)
        _merge_stats(changes,following)
    return advanced,changes


_CANDIDATE_FROM = ('FROM sentinel_price_candidates c\n'
 '   WHERE NOT EXISTS(SELECT 1 FROM sentinel_snapshot_retirements r WHERE '
 'r.candidate_id=c.candidate_id)\n'
 '   AND EXISTS(SELECT 1 FROM sentinel_snapshot_jobs j WHERE j.candidate_id=c.candidate_id)\n'
 '   AND NOT EXISTS(SELECT 1 FROM sentinel_operational_snapshots s WHERE '
 's.candidate_id=c.candidate_id\n'
 '     AND s.publication_version=(SELECT max(version) FROM sentinel_corpus_publications))\n'
 '   AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons x WHERE '
 'x.candidate_id=c.candidate_id\n'
 '     AND x.version=(SELECT max(version) FROM sentinel_snapshot_comparisons))\n'
 '   AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_jobs j WHERE '
 'j.candidate_id=c.candidate_id\n'
 "     AND j.state NOT IN ('REFUSED','ABORTED','PUBLISHED')\n"
 '     AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons x WHERE '
 'x.job_id=j.job_id))\n'
 '   AND NOT EXISTS(SELECT 1 FROM sentinel_operational_snapshots s WHERE '
 's.candidate_id=c.candidate_id\n'
 '     AND NOT EXISTS(SELECT 1 FROM sentinel_action_coverage a WHERE '
 'a.publication_version=s.publication_version))')

_HINTS = (
    ('EXISTS(SELECT 1 FROM sentinel_snapshot_jobs WHERE deadline<=clock_timestamp()\n'
     "   AND state NOT IN ('REFUSED','ABORTED','PUBLISHED') AND reason<>'COMPARISON_ONLY')"),
    'EXISTS(SELECT 1 '+_CANDIDATE_FROM+')',
    None,
    ('EXISTS(SELECT 1 FROM sentinel_snapshot_evidence e\n'
     '   JOIN sentinel_price_candidates c ON e.evidence_sha256 IN '
     '(c.reference_sha256,c.source_evidence_sha256)\n'
     '   JOIN sentinel_snapshot_retirements r USING(candidate_id)\n'
     '   WHERE (e.payload IS NOT NULL OR e.canonical_payload IS NOT NULL)\n'
     '   AND NOT EXISTS(SELECT 1 FROM sentinel_price_candidates live\n'
     '     WHERE e.evidence_sha256 IN (live.reference_sha256,live.source_evidence_sha256)\n'
     '     AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_retirements gone WHERE '
     'gone.candidate_id=live.candidate_id))\n'
     '   AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_validations WHERE '
     'validation_sha256=e.evidence_sha256)\n'
     '   AND NOT EXISTS(SELECT 1 FROM sentinel_operational_snapshot_validations WHERE '
     'validation_sha256=e.evidence_sha256)\n'
     '   AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons WHERE '
     'producer_sha256=e.evidence_sha256))'),
    ('EXISTS(SELECT 1 FROM sentinel_sep_staging s JOIN sentinel_snapshot_workers w ON '
     'w.owner=s.run_id\n'
     '   JOIN sentinel_snapshot_jobs j USING(job_id) WHERE j.owner IS DISTINCT FROM w.owner\n'
     "   AND j.state IN ('REFUSED','ABORTED','PUBLISHED'))"),
    ('EXISTS(SELECT 1 FROM sentinel_acquisition_parts a WHERE NOT '
     'sentinel_acquisition_part_pinned(a.part_id))'),
    ('EXISTS(SELECT 1 FROM sentinel_normalized_blocks b WHERE canonical_payload IS NOT NULL\n'
     ' AND NOT EXISTS(SELECT 1 FROM sentinel_candidate_blocks r WHERE '
     'r.block_sha256=b.block_sha256\n'
     '   AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_retirements gone WHERE '
     'gone.candidate_id=r.candidate_id)))'),
)



def _payload_possible(conn, progress):
    count = _retirement_count(conn)
    return bool(count if progress is None else
                count != progress.known_retirement_count or progress.legacy or progress.active)


def _possible_work(conn):
    """Independent read-only metadata hints; uncertainty is never NO_WORK."""
    from sentinel.feed import normalized_layout
    deadline = time.monotonic()+PROBE_SECONDS
    uncertain = False
    try:
        conn.execute('BEGIN TRANSACTION READ ONLY')
        conn.execute("SET LOCAL lock_timeout='100ms'")
        progress = _read_progress(_Budget(conn,deadline,ceiling_ms=100))
        start = progress.next_class if progress else 0
        for offset in range(7):
            if time.monotonic() >= deadline:
                return True
            class_id = (start+offset)%7
            conn.execute('SAVEPOINT retention_hint')
            try:
                port = _Budget(conn,min(deadline,time.monotonic()+HINT_SECONDS),ceiling_ms=100)
                if class_id == 2:
                    possible = _payload_possible(port,progress)
                elif class_id == 6 and not normalized_layout.available(port):
                    possible = False
                else:
                    if class_id==5:
                        with _pin_planning(port):
                            row = port.execute('SELECT '+_HINTS[class_id]).fetchone()
                    else:
                        row = port.execute('SELECT '+_HINTS[class_id]).fetchone()
                    if row is None or len(row)!=1 or type(row[0]) is not bool:
                        raise RetentionProgressRefused('retention hint is not definite')
                    possible = row[0]
                port.check()
            except Exception:
                conn.execute('ROLLBACK TO SAVEPOINT retention_hint')
                uncertain = True
            else:
                if possible:
                    return True
            finally:
                conn.execute('RELEASE SAVEPOINT retention_hint')
        return uncertain
    finally:
        conn.rollback()


def opening_execution_due(now):
    """Keep disposal and its backup proof away from the actual exchange open."""
    from sentinel.feed import calendar
    day = now.astimezone(timezone.utc).date()
    if not calendar.sessions_in_range(day,day):
        return False
    opened,_ = calendar.session_window(day)
    return opened-timedelta(minutes=15)<=now<opened+timedelta(minutes=10)


class _CandidateRetry(Exception):
    def __init__(self, cause, progress):
        super().__init__(type(cause).__name__)
        self.cause, self.progress = cause, progress


def _candidate_step(conn, progress):
    if progress.legacy is not None or progress.active is not None:
        return progress,_stats()
    predicate, params = '', ()
    if progress.metadata_cursor:
        predicate = ' AND c.candidate_id>%s::uuid'
        params = (progress.metadata_cursor,)
    rows = conn.execute('SELECT c.candidate_id '+_CANDIDATE_FROM
        +predicate+' ORDER BY c.candidate_id LIMIT 32',params).fetchall()
    after, retained = progress, {}
    for (candidate,) in rows:
        candidate = str(candidate)
        attempted = after.model_copy(update={'metadata_cursor':candidate})
        try:
            pins = conn.execute('SELECT sentinel_snapshot_pins(%s::uuid)',(candidate,)).fetchone()[0]
            if pins:
                retained[candidate] = pins
                after = attempted
                continue
            _authorize(conn)
            inserted = conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) '
                'VALUES(%s) ON CONFLICT DO NOTHING RETURNING candidate_id',(candidate,)).fetchone()
        except Exception as exc:
            # This cursor records a round-robin attempt, never eligibility. A
            # cancelled candidate is revisited after this finite metadata sweep.
            raise _CandidateRetry(exc,attempted) from exc
        if inserted is not None:
            after = attempted.model_copy(update={
                'known_retirement_count':after.known_retirement_count+1,
                'active':CandidateCursor(candidate_id=candidate)})
            return after,_stats(retired_candidate_id=candidate,retired_count=1,
                retained=retained,retained_count=len(retained),progress_made=True)
        after = attempted
    more = len(rows)==32
    if not more:
        after = after.model_copy(update={'metadata_cursor':None})
    return after,_stats(retained=retained,retained_count=len(retained),
                        progress_made=more,metadata_more=more)


def _run_class(conn, class_id, progress, *, batch_rows):
    if class_id == 0:
        rows = conn.execute('SELECT job_id FROM sentinel_snapshot_jobs '
            'WHERE deadline<=clock_timestamp() '
            "AND state NOT IN ('REFUSED','ABORTED','PUBLISHED') AND reason<>'COMPARISON_ONLY' "
            'ORDER BY deadline LIMIT 32 FOR UPDATE SKIP LOCKED').fetchall()
        expired = 0
        if rows:
            _authorize(conn)
            for (job,) in rows:
                expired += int(rolling_jobs.expire(conn,str(job)))
        return progress,_stats(progress_made=bool(expired))
    if class_id == 1:
        return _candidate_step(conn,progress)
    if class_id == 2:
        return (_bootstrap_class(conn,progress,batch_rows=batch_rows) if progress.legacy else
                _logical_step(conn,progress,batch_rows=batch_rows))
    if class_id == 3:
        conn.execute('LOCK TABLE sentinel_price_candidates IN SHARE ROW EXCLUSIVE MODE')
        evidence = conn.execute('SELECT DISTINCT e.evidence_sha256 FROM sentinel_snapshot_evidence e '
            'JOIN sentinel_price_candidates c ON e.evidence_sha256 IN (c.reference_sha256,c.source_evidence_sha256) '
            'JOIN sentinel_snapshot_retirements r USING(candidate_id) '
            'WHERE (e.payload IS NOT NULL OR e.canonical_payload IS NOT NULL) '
            'AND NOT EXISTS(SELECT 1 FROM sentinel_price_candidates live WHERE '
            'e.evidence_sha256 IN (live.reference_sha256,live.source_evidence_sha256) AND NOT EXISTS '
            '(SELECT 1 FROM sentinel_snapshot_retirements gone WHERE gone.candidate_id=live.candidate_id)) '
            'AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_validations WHERE validation_sha256=e.evidence_sha256) '
            'AND NOT EXISTS(SELECT 1 FROM sentinel_operational_snapshot_validations WHERE validation_sha256=e.evidence_sha256) '
            'AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons WHERE producer_sha256=e.evidence_sha256) '
            'LIMIT 32').fetchall()
        if evidence:
            _authorize(conn)
            for (sha,) in evidence:
                conn.execute('UPDATE sentinel_snapshot_evidence SET payload=NULL,canonical_payload=NULL '
                             'WHERE evidence_sha256=%s',(sha,))
        return progress,_stats(released_evidence=len(evidence),progress_made=bool(evidence))
    if class_id == 4:
        rows = conn.execute('SELECT s.ctid FROM sentinel_sep_staging s '
            'JOIN sentinel_snapshot_workers w ON w.owner=s.run_id '
            'JOIN sentinel_snapshot_jobs j USING(job_id) WHERE j.owner IS DISTINCT FROM w.owner '
            "AND j.state IN ('REFUSED','ABORTED','PUBLISHED') LIMIT %s FOR UPDATE OF s SKIP LOCKED",
            (batch_rows,)).fetchall()
        deleted = 0
        if rows:
            _authorize(conn)
            deleted = conn.execute('DELETE FROM sentinel_sep_staging WHERE ctid=ANY(%s::tid[])',
                                   ([str(row[0]) for row in rows],)).rowcount
            if deleted != len(rows):
                raise RetentionProgressRefused('selected scratch rows changed')
        return progress,_stats(deleted_scratch_rows=deleted,progress_made=bool(deleted))
    if class_id == 5:
        with _pin_planning(conn):
            return _acquisition_step(conn,progress,batch_rows=batch_rows)
    if class_id == 6:
        from sentinel.feed import normalized_layout
        rows = []
        if normalized_layout.available(conn):
            rows = conn.execute('SELECT b.block_sha256 FROM sentinel_normalized_blocks b '
                'WHERE canonical_payload IS NOT NULL AND NOT EXISTS('
                'SELECT 1 FROM sentinel_candidate_blocks r WHERE r.block_sha256=b.block_sha256 '
                'AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_retirements gone '
                'WHERE gone.candidate_id=r.candidate_id)) ORDER BY b.block_sha256 LIMIT 32').fetchall()
        if rows:
            _authorize(conn)
            for (sha,) in rows:
                conn.execute('UPDATE sentinel_normalized_blocks SET canonical_payload=NULL WHERE block_sha256=%s',
                             (sha,))
        return progress,_stats(released_normalized_blocks=len(rows),progress_made=bool(rows))
    raise ValueError('unknown retention work class')


def _acquisition_step(conn, progress, *, batch_rows):
    disposable = conn.execute('SELECT a.part_id FROM sentinel_acquisition_parts a WHERE NOT '
        'sentinel_acquisition_part_pinned(a.part_id) AND EXISTS '
        '(SELECT 1 FROM sentinel_acquisition_prices p WHERE p.part_id=a.part_id) '
        'ORDER BY a.created_at LIMIT 1 FOR UPDATE OF a SKIP LOCKED').fetchone()
    deleted = 0
    if disposable:
        rows = conn.execute('SELECT ctid FROM sentinel_acquisition_prices WHERE part_id=%s '
            'LIMIT %s FOR UPDATE SKIP LOCKED',
            (disposable[0],min(batch_rows,ACQUISITION_BATCH_ROWS))).fetchall()
        if rows:
            _authorize(conn)
            deleted = conn.execute('DELETE FROM sentinel_acquisition_prices '
                'WHERE part_id=%s AND ctid=ANY(%s::tid[])',
                (disposable[0],[str(row[0]) for row in rows])).rowcount
            if deleted != len(rows):
                raise RetentionProgressRefused('selected acquisition rows changed')
    parts = conn.execute('SELECT a.part_id FROM sentinel_acquisition_parts a WHERE NOT '
        'sentinel_acquisition_part_pinned(a.part_id) AND NOT EXISTS '
        '(SELECT 1 FROM sentinel_acquisition_prices p WHERE p.part_id=a.part_id) '
        'LIMIT 32 FOR UPDATE OF a SKIP LOCKED').fetchall()
    removed = 0
    if parts:
        _authorize(conn)
        removed = conn.execute('DELETE FROM sentinel_acquisition_parts WHERE part_id=ANY(%s::text[])',
                               ([row[0] for row in parts],)).rowcount
    return progress,_stats(deleted_acquisition_rows=deleted,
        deleted_acquisition_parts=removed,progress_made=bool(deleted or removed))


def _merge_stats(total, changes):
    for key,value in changes.items():
        if key=='retained':
            total[key].update(value)
        elif key=='retained_count':
            continue
        elif isinstance(value,bool):
            total[key] = total[key] or value
        elif isinstance(value,int):
            total[key] += value
        elif value is not None:
            total[key] = value
    total['retained_count'] = len(total['retained'])


def _smaller_payload(progress):
    if progress.legacy is not None and progress.legacy.page_quantum>1:
        return progress.model_copy(update={'legacy':progress.legacy.model_copy(update={
            'page_quantum':max(1,progress.legacy.page_quantum//2)})})
    if progress.active is not None and progress.active.row_quantum>1:
        return progress.model_copy(update={'active':progress.active.model_copy(update={
            'row_quantum':max(1,progress.active.row_quantum//2)})})
    return progress


def _pass(conn, *, batch_rows, deadline=None):
    """Caller holds both writer locks; all mutation/progress commits stay outside."""
    deadline = deadline if deadline is not None else time.monotonic()+PASS_SECONDS
    admission_end = deadline-CHECKPOINT_RESERVE
    port = _Budget(conn,admission_end)
    authorization = _Authorization(conn,admission_end)
    progress = _read_progress(port)
    total = _stats()
    if progress is None:
        progress = _initial_progress(port)
        total['progress_made'] = bool(progress.legacy)
        count = progress.known_retirement_count
    else:
        count = _retirement_count(port)
    if count < progress.known_retirement_count:
        raise RetentionProgressRefused('append-only retirement count decreased')
    if count > progress.known_retirement_count:
        progress = progress.model_copy(update={'known_retirement_count':count,
            'active':None,'legacy':_physical_cursor(port,'BARS')})
        total['progress_made'] = True
    start, errors = progress.next_class, {}
    for offset in range(7):
        if time.monotonic() >= admission_end:
            break
        class_id = (start+offset)%7
        before = progress
        conn.execute('SAVEPOINT retention_class')
        work = _Budget(conn,min(admission_end,time.monotonic()+CLASS_SECONDS),
                       ceiling_ms=500,authorization=authorization)
        try:
            after, changes = _run_class(work,class_id,before,batch_rows=batch_rows)
            work.check()
        except Exception as exc:
            conn.execute('ROLLBACK TO SAVEPOINT retention_class')
            if isinstance(exc,_CandidateRetry):
                progress, cause = exc.progress, exc.cause
            else:
                progress, cause = before, exc
            errors[str(class_id)] = type(cause).__name__
            if class_id==2 and cause is not authorization.error and (isinstance(cause,RetentionBudgetExpired)
                               or getattr(cause,'sqlstate',None)=='57014'):
                progress = _smaller_payload(progress)
        else:
            progress = after
            reason = changes.pop('retry_reason',None)
            if reason is not None:
                errors[str(class_id)] = reason
            _merge_stats(total,changes)
        finally:
            conn.execute('RELEASE SAVEPOINT retention_class')
        progress = progress.model_copy(update={'next_class':(class_id+1)%7})
    result = dict(total,status='RETRY' if errors else 'COMPLETE',class_errors=errors,
                  more_work=bool(progress.legacy or progress.active or total['progress_made']
                                 or total['metadata_more']))
    publication = _Budget(conn,deadline,ceiling_ms=1000)
    _write_result(publication,result,progress)
    publication.check()
    return result


def _record_retry(conn, result):
    """Never replace a newer committed cursor with an old failed attempt."""
    conn.execute("SET LOCAL lock_timeout='250ms'")
    conn.execute("SET LOCAL statement_timeout='1s'")
    conn.execute('INSERT INTO sentinel_snapshot_maintenance(id,diagnostic) VALUES(TRUE,%s::jsonb) '
        'ON CONFLICT(id) DO UPDATE SET updated_at=clock_timestamp(),diagnostic=CASE '
        "WHEN jsonb_typeof(sentinel_snapshot_maintenance.diagnostic)='object' THEN "
        'sentinel_snapshot_maintenance.diagnostic || EXCLUDED.diagnostic '
        'ELSE sentinel_snapshot_maintenance.diagnostic END',(canonical_json(result),))
    conn.commit()


def maintain(conn, *, batch_rows=BATCH_ROWS):
    """One bounded pass; disposal and durable progress have a single commit."""
    from sentinel.execution.journal import writer_lock
    if conn.info.transaction_status.value != 0:
        raise RuntimeError('retention requires an idle connection')
    if not 1 <= batch_rows <= 50000:
        raise ValueError('retention batch must be in 1..50000')
    if opening_execution_due(datetime.now(timezone.utc)):
        return dict(status='DEFERRED',reason='OPENING_EXECUTION_WINDOW',more_work=True)
    deadline = time.monotonic()+PASS_SECONDS
    try:
        if not _possible_work(conn):
            return dict(status='COMPLETE',reason='NO_WORK',deleted_rows=0,more_work=False)
        if time.monotonic() >= deadline-CHECKPOINT_RESERVE:
            raise RetentionBudgetExpired('retention admission quantum exhausted')
        with writer_lock(conn),store.corpus_write_lock(conn):
            conn.execute("SET LOCAL lock_timeout='250ms'")
            result = _pass(conn,batch_rows=batch_rows,deadline=deadline)
            conn.commit()
        return result
    except Exception as exc:
        conn.rollback()
        result = dict(status='RETRY',reason=type(exc).__name__,progress_made=False,more_work=False)
        log.warning('rolling maintenance deferred: %s',type(exc).__name__)
        try:
            _record_retry(conn,result)
        except Exception:
            conn.rollback()
            log.warning('rolling maintenance diagnostics unavailable; retry next wake')
        return result


def idle_pass(database_url):
    """Continue only committed useful work, never a loop of unknown retries."""
    conn = None
    try:
        conn = store.connect(database_url,connect_timeout=3,statement_timeout_ms=1000)
        available = conn.execute("SELECT to_regclass('sentinel_operational_snapshots')").fetchone()[0]
        if not available or not conn.execute('SELECT 1 FROM sentinel_operational_snapshots LIMIT 1').fetchone():
            return False
        conn.rollback()
        result = maintain(conn)
        return bool(result.get('progress_made') and result.get('more_work'))
    except Exception as exc:
        log.warning('rolling idle maintenance deferred: %s',type(exc).__name__)
        return False
    finally:
        if conn is not None:
            conn.close()
