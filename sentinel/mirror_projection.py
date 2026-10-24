"""Publication-aware, bounded correction work for retained PAPER mirror plans."""
from __future__ import annotations

from datetime import date
import hmac
import json

from sentinel import mirror_schema
from sentinel.execution import evidence_projection as coverage
from sentinel.feed import calendar

DOMAIN='MIRROR'
ROW_SCHEMA='sentinel.paper-mirror-dependency/1'


def _mirror():
    from sentinel import informational_paper_mirror
    return informational_paper_mirror


def installed(conn):
    return mirror_schema.require_schema(conn,allow_absent=True)


def _signature(value):
    from sentinel.feed.publication import _receipt_hmac
    return _receipt_hmac({'purpose':ROW_SCHEMA,'dependency':value})


def _row(conn,plan_id):
    row=conn.execute('SELECT plan_id,decision_session,effective_session,raw_start,security_ids,symbols,'
        'pending_sha256,payload,hmac_sha256 FROM sentinel_paper_mirror_dependencies WHERE plan_id=%s',
        (plan_id,)).fetchone()
    if row is None: return None
    value=row[7]
    expected={'schema','plan_id','decision_session','effective_session','raw_start','security_ids',
        'symbols','pending_sha256','status','historical_mismatch','material_sha256','checked_publication'}
    if (not isinstance(value,dict) or set(value)!=expected or value.get('schema')!=ROW_SCHEMA
            or not hmac.compare_digest(str(row[8]),_signature(value))):
        raise coverage.EvidenceCoverageRefused('MIRROR_DEPENDENCY_AUTHENTICATION_FAILED')
    observed=[str(row[0]),str(row[1]),str(row[2]),str(row[3]),list(row[4]),list(row[5]),str(row[6])]
    if observed!=[value[key] for key in ('plan_id','decision_session','effective_session','raw_start',
            'security_ids','symbols','pending_sha256')]:
        raise coverage.EvidenceCoverageRefused('MIRROR_DEPENDENCY_COLUMNS_CHANGED')
    pending=_mirror()._load_row(conn,_mirror()._pending_cursor(plan_id),status=_mirror().PENDING)
    if pending is None or pending['record_sha256']!=value['pending_sha256']:
        raise coverage.EvidenceCoverageRefused('MIRROR_PENDING_DEPENDENCY_CHANGED')
    raw_start,_=calendar.action_date_window(pending['decision_session'],pending['effective_session'])
    if (value['decision_session']!=pending['decision_session']
            or value['effective_session']!=pending['effective_session'] or value['raw_start']!=raw_start
            or value['security_ids']!=pending['active_security_ids']
            or value['symbols']!=sorted({symbol.upper() for symbol in pending['active_symbols'].values()})):
        raise coverage.EvidenceCoverageRefused('MIRROR_DEPENDENCY_SCOPE_CHANGED')
    if (value['status'] not in {None,_mirror().NO_UNIT_CHANGE,_mirror().MISMATCH}
            or type(value['historical_mismatch']) is not bool
            or type(value['checked_publication']) is not int or value['checked_publication']<0):
        raise coverage.EvidenceCoverageRefused('MIRROR_DEPENDENCY_RESULT_CHANGED')
    return value


def _write(conn,value):
    conn.execute('INSERT INTO sentinel_paper_mirror_dependencies(plan_id,decision_session,effective_session,'
        'raw_start,security_ids,symbols,pending_sha256,payload,hmac_sha256) '
        'VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT(plan_id) DO UPDATE SET '
        'payload=EXCLUDED.payload,hmac_sha256=EXCLUDED.hmac_sha256',
        (*(value[key] for key in ('plan_id','decision_session','effective_session','raw_start','security_ids',
            'symbols','pending_sha256')),json.dumps(value,sort_keys=True,separators=(',',':')),_signature(value)))


def _index_pending(conn,pending):
    current=_row(conn,pending['plan_id'])
    if current is not None:
        if current['pending_sha256']!=pending['record_sha256']:
            raise coverage.EvidenceCoverageRefused('MIRROR_PENDING_IDENTITY_CHANGED')
        return False
    raw_start,_=calendar.action_date_window(pending['decision_session'],pending['effective_session'])
    value=dict(schema=ROW_SCHEMA,plan_id=pending['plan_id'],decision_session=pending['decision_session'],
        effective_session=pending['effective_session'],raw_start=raw_start,
        security_ids=list(pending['active_security_ids']),
        symbols=sorted({symbol.upper() for symbol in pending['active_symbols'].values()}),
        pending_sha256=pending['record_sha256'],status=None,historical_mismatch=False,
        material_sha256=None,checked_publication=0)
    _write(conn,value)
    return True


def _latch_check(conn,record):
    row=_row(conn,record['plan_id'])
    if row is None:
        raise coverage.EvidenceCoverageRefused('MIRROR_CHECK_WITHOUT_PENDING')
    if record['plan_fingerprint']!=_mirror()._load_row(conn,_mirror()._pending_cursor(record['plan_id']))['plan_fingerprint']:
        raise coverage.EvidenceCoverageRefused('MIRROR_CHECK_PLAN_CHANGED')
    if record['status']==_mirror().MISMATCH and not row['historical_mismatch']:
        row['historical_mismatch']=True;_write(conn,row)
        return True
    return False


def _recheck(conn,plan_id,*,publication_version):
    row=_row(conn,plan_id)
    if row is None: raise coverage.EvidenceCoverageRefused('MIRROR_DEPENDENCY_ABSENT')
    pending=_mirror()._load_row(conn,_mirror()._pending_cursor(plan_id),status=_mirror().PENDING)
    material=_mirror()._material_multipliers(conn,pending=pending)
    was_mismatch=row['historical_mismatch']
    row.update(status=_mirror().MISMATCH if material else _mirror().NO_UNIT_CHANGE,
        historical_mismatch=was_mismatch or bool(material),material_sha256=coverage.digest(material),
        checked_publication=int(publication_version))
    _write(conn,row)
    return row['historical_mismatch'] and not was_mismatch


def _initial_body():
    return dict(stage='PENDING',after='',check_after='',accumulator=coverage.digest(['mirror-bootstrap/1']),
        plan_count=0,historical_mismatch_count=0,checked_publication=0,checked_through=None,
        event_after_plan='')


def bootstrap_step(conn, *, limit=128):
    """Migrate one bounded page of old stamps/checks; never rewrites them."""
    mirror_schema.require_schema(conn)
    if type(limit) is not int or not 1<=limit<=128: raise ValueError('mirror limit must be 1..128')
    _,head,reset=coverage.head(conn,DOMAIN,lock=True)
    if reset: raise coverage.EvidenceCoverageRefused('MIRROR_TRACKING_WAS_RESET')
    state=coverage.load(conn,DOMAIN)
    if state is None:
        if conn.execute("SELECT 1 FROM sentinel_execution_evidence_changes WHERE domain=%s "
                "AND operation<>'INSERT' LIMIT 1",(DOMAIN,)).fetchone():
            raise coverage.EvidenceCoverageRefused('MIRROR_MUTATED_BEFORE_BOOTSTRAP')
        state=coverage.write(conn,DOMAIN,through=0,body=_initial_body())
    body=dict(state['body'])
    if body['stage']=='COMPLETE': return state
    # Own index inserts are authenticated below. All other changes require a
    # quiescent explicit migration, rather than a moving historical baseline.
    incoming=coverage.changes(conn,DOMAIN,state['through'],limit=128)
    for sequence,source,key,operation,detail in incoming:
        if source!='sentinel_paper_mirror_dependencies' or operation not in {'INSERT','UPDATE'}:
            raise coverage.EvidenceCoveragePending('MIRROR_BOOTSTRAP_REQUIRES_QUIESCENT_SOURCE')
        _row(conn,key)
    through=int(incoming[-1][0]) if incoming else state['through']
    if through!=head:
        return coverage.write(conn,DOMAIN,through=through,body=body)
    page=max(1,min(limit,32))  # one stamp may also append its index witness.
    if body['stage']=='PENDING':
        rows=conn.execute("SELECT cursor_name,session,state FROM sentinel_processed_sessions "
            "WHERE cursor_name LIKE 'informational-paper-mirror:v1:%%:pending' AND cursor_name>%s "
            "ORDER BY cursor_name LIMIT %s",(body['after'],page)).fetchall()
        for name,session,raw in rows:
            record=_mirror()._validate(raw,status=_mirror().PENDING)
            if str(session)!=record['effective_session'] or name!=_mirror()._pending_cursor(record['plan_id']):
                raise coverage.EvidenceCoverageRefused('MIRROR_PENDING_CURSOR_CHANGED')
            if _index_pending(conn,record): body['plan_count']+=1
            body['after']=name;body['accumulator']=coverage.digest([body['accumulator'],record['record_sha256']])
        if len(rows)<page: body['stage']='CHECKS'
    elif body['stage']=='CHECKS':
        rows=conn.execute("SELECT cursor_name,session,state FROM sentinel_processed_sessions "
            "WHERE cursor_name LIKE 'informational-paper-mirror:v1:%%:check:%%' AND cursor_name>%s "
            "ORDER BY cursor_name LIMIT %s",(body['check_after'],page)).fetchall()
        for name,session,raw in rows:
            record=_mirror()._validate(raw)
            if (record['status']==_mirror().PENDING or str(session)!=record['effective_session']
                    or name!=_mirror()._check_cursor(record['plan_id'],record['checked_publication_version'])):
                raise coverage.EvidenceCoverageRefused('MIRROR_CHECK_CURSOR_CHANGED')
            if _latch_check(conn,record): body['historical_mismatch_count']+=1
            body['check_after']=name;body['accumulator']=coverage.digest([body['accumulator'],record['record_sha256']])
        if len(rows)<page: body['stage']='COMPLETE'
    else: raise coverage.EvidenceCoverageRefused('MIRROR_BOOTSTRAP_STAGE_CHANGED')
    return coverage.write(conn,DOMAIN,through=through,body=body)


def _coordinate_conditions(conn,source,detail):
    clauses=[];params=[]
    if detail.get('kind')=='unknown': return 'TRUE',[]
    if detail.get('kind')=='plan': return 'plan_id=%s',[detail['plan_id']]
    for coordinate in (detail.get('before'),detail.get('after')):
        if coordinate is None: continue
        if not isinstance(coordinate,dict) or not coordinate.get('session'):
            return 'TRUE',[]
        try: day=date.fromisoformat(coordinate['session'])
        except (TypeError,ValueError): return 'TRUE',[]
        # Raw ex-dates can map through holidays. The indexed raw_start was
        # derived from the same canonical XNYS action-date window.
        ids=[str(coordinate.get('security_id') or '')]
        symbols=[str(coordinate.get(key) or '').upper() for key in ('ticker','contraticker')]
        if source=='sentinel_defensive_bars':
            clauses.append('(effective_session>=%s AND security_ids && %s::text[])')
            params.extend((day,['SENTINEL:BIL']))
        else:
            clauses.append('(raw_start<=%s AND effective_session>=%s AND '
                '(security_ids && %s::text[] OR symbols && %s::text[]))')
            params.extend((day,day,ids,symbols))
    return (' OR '.join(clauses),params) if clauses else ('TRUE',[])


def _retained_conditions(conn,version):
    """Select changed old/new action dates, rather than every retained plan."""
    rows=conn.execute('SELECT c.publication_version,c.payload,c.payload_sha256,p.evidence '
        'FROM sentinel_action_coverage c JOIN sentinel_corpus_publications p ON p.version=c.publication_version '
        'WHERE c.publication_version<=%s ORDER BY c.publication_version DESC LIMIT 2',(version,)).fetchall()
    if not rows or int(rows[0][0])!=int(version): return 'TRUE',[]
    for number,payload,digest,evidence in rows:
        if (not isinstance(evidence,dict) or coverage.digest(payload)!=digest
                or evidence.get('action_history')!=digest):
            raise coverage.EvidenceCoverageRefused('MIRROR_RETAINED_COVERAGE_AUTHENTICATION_FAILED')
    current=rows[0][1];previous=rows[1][1] if len(rows)>1 else {}
    if not isinstance(current,dict) or not isinstance(previous,dict): return 'TRUE',[]
    added=current.get('added');corrections=current.get('corrections')
    old_corrections=previous.get('corrections',[])
    if not isinstance(added,dict) or not isinstance(corrections,list) or not isinstance(old_corrections,list):
        return 'TRUE',[]
    before={coverage.digest(item):item for item in old_corrections}
    after={coverage.digest(item):item for item in corrections}
    changed=[before[key] for key in before.keys()-after.keys()]+[after[key] for key in after.keys()-before.keys()]
    coordinates=[{'session':day} for day in added]
    for item in changed:
        if not isinstance(item,dict) or not isinstance(item.get('session'),str): return 'TRUE',[]
        coordinates.append({key:item.get(key) for key in ('session','security_id','ticker','contraticker')})
    try:
        for item in coordinates: item['session']=date.fromisoformat(item['session']).isoformat()
    except (TypeError,ValueError): return 'TRUE',[]
    if not coordinates: return 'FALSE',[]
    return ("EXISTS(SELECT 1 FROM jsonb_array_elements(%s::jsonb) changed "
        "WHERE (changed->>'session')::date>=d.raw_start AND (changed->>'session')::date<=d.effective_session "
        "AND (changed->>'security_id'=ANY(d.security_ids) OR upper(changed->>'ticker')=ANY(d.symbols) "
        "OR upper(changed->>'contraticker')=ANY(d.symbols) OR "
        "COALESCE(changed->>'security_id',changed->>'ticker',changed->>'contraticker') IS NULL))"),[json.dumps(coordinates)]


def _publication_conditions(conn,detail):
    value=detail.get('after')
    if not isinstance(value,dict): return 'TRUE',[]
    run=value.get('run_id')
    evidence=value.get('evidence') or {}
    if not isinstance(evidence,dict): return 'TRUE',[]
    if 'rolling_snapshot' in evidence:
        if not evidence.get('action_history'): return 'TRUE',[]
        return _retained_conditions(conn,value.get('version'))
    conditions=[];params=[]
    for table in ('sentinel_actions','sentinel_action_observations','sentinel_corpus_anomalies'):
        symbol_match='upper(s.ticker)=ANY(d.symbols)'
        if table!='sentinel_corpus_anomalies': symbol_match+=' OR upper(s.contraticker)=ANY(d.symbols)'
        conditions.append(f'EXISTS(SELECT 1 FROM {table} s WHERE s.last_written_run_id::text=%s '
            'AND s.session>=d.raw_start AND s.session<=d.effective_session AND ('+symbol_match+'))')
        params.append(run)
    for table in ('sentinel_bars','sentinel_bar_split_repairs'):
        identity='s.security_id=ANY(d.security_ids)'
        if table=='sentinel_bars': identity+=' OR upper(s.ticker)=ANY(d.symbols)'
        conditions.append(f'EXISTS(SELECT 1 FROM {table} s WHERE s.last_written_run_id::text=%s '
            'AND s.session>=d.raw_start AND s.session<=d.effective_session AND ('+identity+'))')
        params.append(run)
    conditions.append('EXISTS(SELECT 1 FROM sentinel_defensive_bars s WHERE s.last_written_run_id::text=%s '
        "AND s.session<=d.effective_session AND 'SENTINEL:BIL'=ANY(d.security_ids))")
    params.append(run)
    retirement=evidence.get('source_retirement') if isinstance(evidence,dict) else None
    if retirement is not None:
        keys=retirement.get('keys') if isinstance(retirement,dict) else None
        if not isinstance(keys,list): return 'TRUE',[]
        conditions.append('EXISTS(SELECT 1 FROM jsonb_array_elements(%s::jsonb) k '
            "WHERE k->>'security_id'=ANY(d.security_ids) AND (k->>'session')::date>=d.raw_start "
            "AND (k->>'session')::date<=d.effective_session)")
        params.append(json.dumps(keys))
    return ' OR '.join(conditions),params


def _consume_event(conn,event,body,*,through,publication_version,budget):
    sequence,source,key,operation,detail=event
    if operation=='TRUNCATE': raise coverage.EvidenceCoverageRefused('MIRROR_SOURCE_WAS_TRUNCATED')
    kind=detail.get('kind') if isinstance(detail,dict) else None
    if kind=='projection':
        if operation not in {'INSERT','UPDATE'} or _row(conn,key) is None:
            raise coverage.EvidenceCoverageRefused('MIRROR_PROJECTION_MUTATED')
        return True,1
    if kind=='legacy':
        if operation!='INSERT': raise coverage.EvidenceCoverageRefused('MIRROR_HISTORY_MUTATED')
        record=_mirror()._load_row(conn,key)
        if record is None: raise coverage.EvidenceCoverageRefused('MIRROR_HISTORY_MISSING')
        if record['status']==_mirror().PENDING:
            if key!=_mirror()._pending_cursor(record['plan_id']):
                raise coverage.EvidenceCoverageRefused('MIRROR_PENDING_CURSOR_CHANGED')
            if _index_pending(conn,record): body['plan_count']+=1
        elif _latch_check(conn,record): body['historical_mismatch_count']+=1
        return True,1
    if kind=='publication':
        if operation!='INSERT': raise coverage.EvidenceCoverageRefused('MIRROR_PUBLICATION_HISTORY_MUTATED')
        condition,params=_publication_conditions(conn,detail)
    elif kind=='retained_history':
        if operation!='INSERT': raise coverage.EvidenceCoverageRefused('MIRROR_RETAINED_HISTORY_MUTATED')
        try: day=date.fromisoformat(detail['session'])
        except (KeyError,TypeError,ValueError):
            raise coverage.EvidenceCoverageRefused('MIRROR_RETAINED_COORDINATE_CHANGED') from None
        condition,params='d.raw_start<=%s AND d.effective_session>=%s',[day,day]
    elif kind=='retained_coverage':
        if operation!='INSERT': raise coverage.EvidenceCoverageRefused('MIRROR_RETAINED_COVERAGE_MUTATED')
        try: version=int(detail['publication_version'])
        except (KeyError,TypeError,ValueError):
            raise coverage.EvidenceCoverageRefused('MIRROR_RETAINED_COORDINATE_CHANGED') from None
        condition,params=_retained_conditions(conn,version)
    elif kind=='plan':
        condition,params='d.plan_id=%s',[key]
    elif kind in {'coordinate','unknown'}:
        condition,params=_coordinate_conditions(conn,source,detail)
    else: raise coverage.EvidenceCoverageRefused('MIRROR_CHANGE_KIND_UNKNOWN')
    rows=conn.execute('SELECT d.plan_id FROM sentinel_paper_mirror_dependencies d WHERE d.plan_id>%s '
        'AND d.effective_session<=%s AND ('+condition+') ORDER BY d.plan_id LIMIT %s',
        (body['event_after_plan'],through,*params,budget)).fetchall()
    for (plan_id,) in rows:
        if _recheck(conn,plan_id,publication_version=publication_version): body['historical_mismatch_count']+=1
        body['event_after_plan']=plan_id
    complete=len(rows)<budget
    if complete: body['event_after_plan']=''
    return complete,max(1,len(rows))


def advance(conn, *, checked_through,publication_version,limit=128):
    """Consume at most ``limit`` source/plan units inside caller ownership."""
    mirror_schema.require_schema(conn)
    if type(limit) is not int or not 1<=limit<=128: raise ValueError('mirror limit must be 1..128')
    coverage.head(conn,DOMAIN,lock=True)
    state=coverage.load(conn,DOMAIN)
    if state is None or state['body'].get('stage')!='COMPLETE':
        raise coverage.EvidenceCoveragePending('MIRROR_BOOTSTRAP_REQUIRED')
    through=str(checked_through);body=dict(state['body']);boundary=state['through'];used=0
    actual=conn.execute('SELECT window_end FROM sentinel_corpus_publications WHERE version=%s',
        (publication_version,)).fetchone()
    if actual is None or str(actual[0])!=through:
        raise coverage.EvidenceCoverageRefused('MIRROR_PUBLICATION_SUBJECT_CHANGED')
    while used<limit:
        rows=coverage.changes(conn,DOMAIN,boundary,limit=1)
        if not rows: break
        complete,cost=_consume_event(conn,rows[0],body,through=through,
            publication_version=publication_version,budget=limit-used)
        used+=cost
        if not complete: break
        boundary=int(rows[0][0])
        body['accumulator']=coverage.digest([body['accumulator'],list(rows[0])])
    if used<limit:
        due=conn.execute("SELECT plan_id FROM sentinel_paper_mirror_dependencies WHERE effective_session<=%s "
            "AND payload->>'status' IS NULL ORDER BY plan_id LIMIT %s",(through,limit-used)).fetchall()
        for (plan_id,) in due:
            if _recheck(conn,plan_id,publication_version=publication_version): body['historical_mismatch_count']+=1
            used+=1
    # Newly signed row changes remain journalled. A later bounded pass proves
    # their exact rows before the prefix becomes current; no unsigned queue is
    # deleted to manufacture readiness.
    if boundary==coverage.head(conn,DOMAIN)[1] and not conn.execute(
            "SELECT 1 FROM sentinel_paper_mirror_dependencies WHERE effective_session<=%s "
            "AND payload->>'status' IS NULL LIMIT 1",(through,)).fetchone():
        body['checked_publication']=int(publication_version);body['checked_through']=through
    return coverage.write(conn,DOMAIN,through=boundary,body=body)


def require_current(conn, *, current_frontier,current_publication_version):
    state=coverage.require_current(conn,DOMAIN)
    body=state['body']
    if (body['checked_publication']!=int(current_publication_version)
            or body['checked_through']!=str(current_frontier)):
        raise coverage.EvidenceCoveragePending('MIRROR_CURRENT_PUBLICATION_PENDING')
    future=conn.execute('SELECT plan_id FROM sentinel_paper_mirror_dependencies WHERE effective_session>%s '
        'ORDER BY plan_id LIMIT 129',(str(current_frontier),)).fetchall()
    if len(future)>128: raise coverage.EvidenceCoveragePending('MIRROR_FUTURE_PLAN_PAGE_REQUIRED')
    return dict(schema=_mirror().SCHEMA,status=(_mirror().MISMATCH if body['historical_mismatch_count']
        else _mirror().PENDING if future else _mirror().NO_UNIT_CHANGE),pending_sessions=len(future),
        historical_mismatch_count=body['historical_mismatch_count'],verdict='PAPER_NOT_VERIFIED')


def plan_status(conn, *, plan_id,plan_fingerprint,current_frontier,current_publication_version):
    require_current(conn,current_frontier=current_frontier,current_publication_version=current_publication_version)
    row=_row(conn,plan_id)
    if row is None: raise _mirror().InformationalPaperMirrorUnstamped('current plan has no indexed mirror stamp')
    pending=_mirror()._load_row(conn,_mirror()._pending_cursor(plan_id))
    if pending['plan_fingerprint']!=plan_fingerprint:
        raise coverage.EvidenceCoverageRefused('MIRROR_CURRENT_PLAN_IDENTITY_CHANGED')
    if row['historical_mismatch']:
        raise _mirror().InformationalPaperMirrorMismatch('current plan has a retained share-unit mismatch')
    if row['effective_session']>str(current_frontier):
        return dict(schema=_mirror().SCHEMA,status=_mirror().PENDING,plan_id=plan_id,verdict='PAPER_NOT_VERIFIED')
    if row['status']!=_mirror().NO_UNIT_CHANGE:
        raise coverage.EvidenceCoveragePending('MIRROR_CURRENT_PLAN_CHECK_PENDING')
    return dict(schema=_mirror().SCHEMA,status=_mirror().NO_UNIT_CHANGE,plan_id=plan_id,verdict='PAPER_NOT_VERIFIED')
