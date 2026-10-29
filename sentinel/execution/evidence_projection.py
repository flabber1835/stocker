"""Authenticated, incarnation-bound coverage primitives; no readiness cache."""
from __future__ import annotations

import hashlib
import hmac
import json

from . import evidence_schema

SCHEMA = 'sentinel.execution-evidence-coverage/1'


class EvidenceCoverageRefused(RuntimeError):
    pass


class EvidenceCoveragePending(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        default=str,allow_nan=False).encode()).hexdigest()


def _signature(payload):
    from sentinel.feed.publication import _receipt_hmac
    return _receipt_hmac({'purpose':SCHEMA,'coverage':payload})


def binding(conn):
    row=conn.execute('SELECT deployment_id,broker,broker_account_id,takeover_epoch,'
        'ownership_state,established_at FROM sentinel_account_binding WHERE id=1').fetchone()
    return None if row is None else [str(value) for value in row]


def _inventory_material(conn, domain):
    from sentinel import operational_ddl_epoch
    from sentinel.operational_catalog import OperationalCatalogRefused
    tables=set(evidence_schema.extension_tables)|set(evidence_schema._SOURCES)
    tables.update(operational_ddl_epoch.extension_tables)
    contracts=[evidence_schema.CONTRACT_SHA256,operational_ddl_epoch.CONTRACT_SHA256]
    try: ddl_epoch=operational_ddl_epoch.current(conn)
    except OperationalCatalogRefused as exc:
        raise EvidenceCoverageRefused(str(exc)) from exc
    if domain=='MIRROR':
        from sentinel import mirror_schema
        mirror_schema.require_schema(conn)
        tables.update(mirror_schema.extension_tables)
        tables.update(mirror_schema.source_tables)
        contracts.append(mirror_schema.CONTRACT_SHA256)
    rows=conn.execute("SELECT c.relname,c.oid::text,pg_relation_filenode(c.oid)::text "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY c.relname",(sorted(tables),)).fetchall()
    if {row[0] for row in rows}!=tables:
        raise EvidenceCoverageRefused('EVIDENCE_SOURCE_RELATION_ABSENT')
    system=conn.execute('SELECT system_identifier::text,current_database() FROM pg_control_system()').fetchone()
    return [contracts,system,rows,ddl_epoch]


def inventory(conn, domain):
    return digest(_inventory_material(conn,domain))


def head(conn, domain, *, lock=False):
    row=conn.execute('SELECT incarnation::text,head_seq,reset_generation '
        'FROM sentinel_execution_evidence_heads WHERE domain=%s'+(' FOR UPDATE' if lock else ''),
        (domain,)).fetchone()
    if row is None:
        raise EvidenceCoverageRefused('EVIDENCE_TRACKING_HEAD_ABSENT')
    return str(row[0]),int(row[1]),int(row[2])


def _authenticated(conn, domain):
    row=conn.execute('SELECT payload,hmac_sha256 FROM sentinel_execution_evidence_coverage '
        'WHERE domain=%s',(domain,)).fetchone()
    if row is None:
        return None
    payload=row[0]
    if not isinstance(payload,dict):
        raise EvidenceCoverageRefused('EVIDENCE_COVERAGE_SHAPE_CHANGED')
    if set(payload)!={'schema','domain','incarnation','through','reset_generation','binding','inventory','body'}:
        raise EvidenceCoverageRefused('EVIDENCE_COVERAGE_SHAPE_CHANGED')
    if payload['schema']!=SCHEMA or payload['domain']!=domain or not isinstance(payload['body'],dict):
        raise EvidenceCoverageRefused('EVIDENCE_COVERAGE_SUBJECT_CHANGED')
    if not hmac.compare_digest(str(row[1]),_signature(payload)):
        raise EvidenceCoverageRefused('EVIDENCE_COVERAGE_AUTHENTICATION_FAILED')
    return payload


def load(conn, domain):
    payload=_authenticated(conn,domain)
    if payload is None:
        return None
    incarnation,sequence,reset=head(conn,domain)
    if (payload['incarnation']!=incarnation or payload['reset_generation']!=reset
            or payload['binding']!=binding(conn) or payload['inventory']!=inventory(conn,domain)
            or type(payload['through']) is not int or not 0<=payload['through']<=sequence):
        raise EvidenceCoverageRefused('EVIDENCE_COVERAGE_BINDING_CHANGED')
    return payload


def write(conn,domain,*,through,body):
    incarnation,sequence,reset=head(conn,domain)
    if type(through) is not int or not 0<=through<=sequence:
        raise EvidenceCoverageRefused('EVIDENCE_COVERAGE_BOUNDARY_CHANGED')
    payload=dict(schema=SCHEMA,domain=domain,incarnation=incarnation,through=through,
        reset_generation=reset,binding=binding(conn),inventory=inventory(conn,domain),body=body)
    conn.execute('INSERT INTO sentinel_execution_evidence_coverage(domain,payload,hmac_sha256) '
        'VALUES(%s,%s::jsonb,%s) ON CONFLICT(domain) DO UPDATE SET payload=EXCLUDED.payload,'
        'hmac_sha256=EXCLUDED.hmac_sha256,updated_at=clock_timestamp()',
        (domain,json.dumps(payload,sort_keys=True,separators=(',',':')),_signature(payload)))
    return payload


def changes(conn,domain,after,*,limit):
    if type(limit) is not int or not 1<=limit<=128:
        raise ValueError('evidence work limit must be between 1 and 128')
    rows=conn.execute('SELECT seq,source,evidence_key,operation,detail '
        'FROM sentinel_execution_evidence_changes WHERE domain=%s AND seq>%s '
        'ORDER BY seq LIMIT %s',(domain,after,limit)).fetchall()
    expected=after+1
    for row in rows:
        if int(row[0])!=expected:
            raise EvidenceCoverageRefused('EVIDENCE_CHANGE_SEQUENCE_GAP')
        expected+=1
    if not rows and head(conn,domain)[1]!=after:
        raise EvidenceCoverageRefused('EVIDENCE_CHANGE_PREFIX_TRUNCATED')
    return rows


def require_current(conn,domain):
    payload=load(conn,domain)
    if payload is None:
        raise EvidenceCoveragePending('EVIDENCE_COVERAGE_BOOTSTRAP_REQUIRED')
    if payload['body'].get('stage')!='COMPLETE' or payload['through']!=head(conn,domain)[1]:
        raise EvidenceCoveragePending('EVIDENCE_COVERAGE_ADVANCE_REQUIRED')
    return payload
