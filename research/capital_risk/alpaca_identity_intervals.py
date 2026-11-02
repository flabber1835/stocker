"""Research-only temporal identity diagnosis over immutable provider metadata.

No prices, returns, portfolio state, financial transitions or broker calls.
The output is a conservative admission proposal, not fabricated IPO metadata.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal,InvalidOperation
import hashlib
import json
import re

from pydantic import BaseModel,ConfigDict,Field


def need(value,reason):
    if not value:raise ValueError('REFUSED_IDENTITY_INTERVAL_'+reason)


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class PrimaryBoundary(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    asset_id:str
    not_before:date
    primary_url:str=Field(pattern='^https://www.sec.gov/Archives/')
    extraction_sha256:str=Field(pattern='^[a-f0-9]{64}$')
    meaning:str=Field(pattern='^(FIRST_SEPARATE_COMMON_TRADING|CURRENT_ISSUE_EFFECTIVE)$')


def parsed_date(value):
    if not isinstance(value,str):return None
    try:return value if date.fromisoformat(value).isoformat()==value else None
    except ValueError:return None


def valid_common_separation(record):
    if not all(isinstance(record.get(k),str) and re.fullmatch('[A-Z0-9]{9}',record[k])
               for k in ('old_cusip','new_cusip')):return False
    try:
        rates=[Decimal(str(record[k])) for k in ('old_rate','new_rate')]
        return all(v.is_finite() and v>0 for v in rates)
    except (KeyError,InvalidOperation,ValueError):return False


def valid_name_identity(record):
    return all(isinstance(record.get(k),str) and re.fullmatch('[A-Z0-9]{9}',record[k]) for k in ('old_cusip','new_cusip')) and all(
        isinstance(record.get(k),str) and 0<len(record[k])<=32 and record[k]==record[k].strip().upper() for k in ('old_symbol','new_symbol'))


def diagnose(classified,actions,*,asof,primary_boundaries=()):
    need(parsed_date(asof) is not None,'ASOF')
    by_ticker={r['ticker']:r for r in classified};by_id={r['asset_id']:r for r in classified}
    need(len(by_ticker)==len(by_id)==len(classified),'UNIQUE_CURRENT_ROSTER')
    departures=defaultdict(list);arrivals=defaultdict(list);unknown=defaultdict(list)
    for kind,r in actions:
        record=digest(r)
        if kind=='name_changes':
            day=parsed_date(r.get('process_date'));old,new=r.get('old_symbol'),r.get('new_symbol')
            if day is None or not valid_name_identity(r):
                for symbol in (old,new):
                    if symbol in by_ticker:unknown[symbol].append({'record_sha256':record,'reason':'UNPROVEN_NAME_IDENTITY'})
                continue
            if day>asof:continue
            if old!=new and old in by_ticker:
                # A current old-name listing cannot inherit the departed issue
                # merely because the literal symbol was reused later.
                same=(new in by_ticker and by_ticker[old]['share_class_figi']==by_ticker[new]['share_class_figi'])
                if not same:departures[old].append((day,record,'OLD_SYMBOL_LEFT_PRIOR_ISSUE'))
            if new in by_ticker and r.get('old_cusip')!=r.get('new_cusip'):
                arrivals[new].append((day,record,'CHANGED_CUSIP_SUCCESSOR_BOUNDARY'))
        elif kind in ('cash_mergers','stock_mergers','cash_stock_mergers','stock_and_cash_mergers'):
            day=parsed_date(r.get('effective_date'));target=r.get('acquiree_symbol')
            if target not in by_ticker:continue
            if day is None:unknown[target].append({'record_sha256':record,'reason':'UNDATED_ACQUIRED_IDENTITY'})
            elif day<=asof:departures[target].append((day,record,'ACQUIRED_PRIOR_ISSUE'))
        elif kind=='unit_splits':
            symbol=r.get('new_symbol');day=parsed_date(r.get('effective_date'))
            if symbol not in by_ticker:continue
            if day is None or not valid_common_separation(r):unknown[symbol].append({'record_sha256':record,'reason':'UNPROVEN_COMMON_SEPARATION'})
            elif day<=asof and r.get('old_symbol')!=symbol and r.get('old_cusip')!=r.get('new_cusip'):
                # This is a conservative common-issue admission boundary, not
                # a claim that the parent unit or company did not exist earlier.
                arrivals[symbol].append((day,record,'SEPARATE_COMMON_ISSUE_BOUNDARY'))
    overrides={}
    for raw in primary_boundaries:
        b=PrimaryBoundary.model_validate(raw);need(b.asset_id in by_id and str(b.not_before)<=asof,'PRIMARY_CURRENT_ID_AND_DATE')
        need(b.asset_id not in overrides,'DUPLICATE_PRIMARY_BOUNDARY');overrides[b.asset_id]=b
    result={};duplicates=defaultdict(list)
    for r in classified:duplicates[r['share_class_figi']].append(r['asset_id'])
    duplicate_ids={sid for ids in duplicates.values() if len(ids)>1 for sid in ids}
    for symbol,r in sorted(by_ticker.items()):
        sid=r['asset_id'];left=sorted(departures[symbol]);entered=sorted(arrivals[symbol]);last_left=left[-1][0] if left else None
        later=[v for v in entered if last_left is None or v[0]>last_left]
        boundary=later[-1] if later else None;primary=overrides.get(sid)
        if primary:
            need(last_left is None or str(primary.not_before)>last_left,'PRIMARY_MUST_FOLLOW_DEPARTED_ISSUE')
            boundary=(str(primary.not_before),primary.extraction_sha256,primary.meaning)
        reasons=list(unknown[symbol])
        if last_left and boundary is None:reasons.append({'reason':'REUSED_OR_STALE_CURRENT_SYMBOL_WITHOUT_SUCCESSOR_BOUNDARY','record_sha256':left[-1][1]})
        if sid in duplicate_ids:reasons.append({'reason':'DUPLICATE_CURRENT_SHARE_CLASS','share_class_figi':r['share_class_figi']})
        result[sid]={'ticker':symbol,'share_class_figi':r['share_class_figi'],'status':'QUARANTINE' if reasons else 'TEMPORAL_ADMISSION_CANDIDATE',
            'not_before':None if boundary is None else boundary[0],'boundary_evidence_sha256':None if boundary is None else boundary[1],
            'boundary_kind':None if boundary is None else boundary[2],'primary_boundary':None if primary is None else primary.model_dump(mode='json'),
            'departures':[{'session':d,'record_sha256':h,'reason':k} for d,h,k in left],'quarantine_reasons':reasons}
    return {'schema':'research.temporal-identity-diagnosis/1','asof':asof,'classification_sha256':digest(classified),
        'actions_sha256':digest(sorted((kind,digest(r)) for kind,r in actions)),'identities':result,
        'duplicate_current_share_class_groups':[sorted(ids) for ids in duplicates.values() if len(ids)>1],
        'uses_price_returns_or_holdings':False,'guarantees_complete_issuer_history':False,
        'current_cohort_survivor_conditioned':True,'financial_origin_created':False,'production_contacted':False}
