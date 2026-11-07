"""Complete source-bound18-term factual selection; financial lifecycle separate."""
import csv,io,json,math,zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import system_campaign_p05_ctxs_data as own
import system_campaign_cash_calendar as cash
import system_campaign_stock_calendar as stock
from system_campaign_facts import sha,digest
from full_system_benchmark import need
HERE=Path(__file__).parent
PINS={'P05-retained-stock-DATA-qualification.json':'a80eccae343a4495c32e64753edd67eaaab93bd30915dadae507b367bbc1261b',
    'P05-retained-NEXT-cash-DATA-qualification.json':'1d3dcb91f924e5faebdb17a220d4a5c1a5e918cbe3d4009e7b9534536b83364c',
    'P05-retained-DRE-LSI-MTTR-stock-DATA-review.json':'47471fba1720b3c3b5327ed3509d6756ceef15af4d6962fb6a28846718b54864',
    'P05-retained14-NEXT-cash-DATA-review.json':'d055c9ed6e4727b0ee1f03b97d5e1a294eb2654d90420f7565e09823cad98888'}
STOCKS=frozenset(('518054177581800417','753641750484343508','268723442486744870'))
CATALOG='P05-own1175-retained18-source-stock-cash-catalog.json'
def source_names():
    return (Path(__file__).name,'system_campaign_p05_remaining_batch_api.py',*own.source_names(),*PINS,
        'system_campaign_stock_calendar.py','system-campaign-stock-calendar-terminal-facts.json')
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def records():
    values={}
    for name,pin in PINS.items():
        raw=(HERE/name).read_bytes();need(sha(raw)==pin,'P05_REMAINING18_ENTIRE_QUALIFIED_REUSE_BYTES:'+name);values[name]=json.loads(raw)
    sq,cq,sr,cr=[values[n] for n in PINS]
    for q,r,name in ((sq,sr,'P05-retained-DRE-LSI-MTTR-stock-DATA-review.json'),(cq,cr,'P05-retained14-NEXT-cash-DATA-review.json')):
        need(q['passed'] is r['passed'] is True and q['review_sha256']==PINS[name]
            and all(q[k] is r[k] is False for k in ('financial_authority','input_adopted','local_canonical_runtime_executed'))
            and r['root_admission_sha256']==own.ROOT and r['full_parent_inputs']==19,
            'P05_REMAINING18_CLOSED_DATA_ONLY_REUSE_NOT_FINANCIAL_AUTHORITY')
    need(len(sr['terms'])==3 and len(cr['terms'])==14,'P05_REMAINING18_EXACT14_CASH_AND3_STOCK')
    return sr,cr
def terms():
    sr,cr=records();payload,review,q=own.records();result=[own.term()]
    capture=dict(run_id=review['run_id'],head=review['head'],artifact_id=review['artifact_id'],
        payload_sha256=q['payload_sha256'],scope_sha256=q['scope_sha256'],independent_data_review_sha256=q['review_sha256'],
        independent_qualification_sha256=own.PINS['P05-CTX-source-qualification-v1.json'])
    for family,group in (('stock',sr['terms']),('cash',cr['terms'])):
        for value in group:
            old=value['original_term'];source=value['fresh_source_term'];term=deepcopy(old)
            need(digest(old)==value['original_term_sha256'] and source in payload['terms']
                and source['parent_positions']==[] and digest(source['native_term'])==old['native_term_sha256'],
                'P05_REMAINING18_EXACT_RETAINED_LITERAL_AND_FRESH_SOURCE_MEMBER')
            term.update(arm='P05',parent_cursor='2022-08-31',parent_outer_sha256=own.OUTER,parent_root_admission_sha256=own.ROOT,
                parent_positions=[],identity_witness=deepcopy(source['identity_witness']),native=deepcopy(source['native_term']),source_capture=deepcopy(capture))
            if family=='cash':
                term['retained_original_cash_term']=dict(catalog_file=value['original_catalog_file'],catalog_sha256=value['original_catalog_sha256'],term_sha256=value['original_term_sha256'])
                cash.validate_term(term)
            else:
                term['retained_original_stock_term']=dict(catalog_file=sr['original_catalog_file'],catalog_sha256=sr['original_catalog_sha256'],term_sha256=value['original_term_sha256'])
                stock.validate_term(term)
            term.setdefault('timing_source',term['primary_source']);result.append(term)
    result.sort(key=lambda t:(t['native_session'],t['security_id']))
    need(len(result)==len({t['security_id'] for t in result})==18 and result[0]['ticker']=='CTXS'
        and {t['security_id'] for t in result if t['added']['kind']!='CASH_MERGER'}==STOCKS,
        'P05_REMAINING18_EXACT_STABLE_DISJOINT_BATCH_AND_ONE_SOURCE_ONLY_TERM')
    return result
def stock_term(term):
    expected=[t for t in terms() if t['security_id']==term['security_id'] and t['added']['kind']!='CASH_MERGER']
    need(len(expected)==1 and encoded(term)==encoded(expected[0]),'P05_REMAINING18_ONLY_EXACT_THREE_RETAINED_STOCK_TERMS')
    stock.validate_term(term)
    return term
def completion_session(term,dates):
    if term['security_id'] not in STOCKS:return own.future.completion_session(term,dates)
    stock_term(term)
    need(dates==sorted(set(dates)) and term['last_trading_session'] in dates
        and dates.index(term['last_trading_session'])+1<len(dates)
        and dates[dates.index(term['last_trading_session'])+1]==term['added']['session']==term['actual_completion_date'],
        'P05_REMAINING18_ORIGINAL_STOCK_ADJACENT_FROZEN_COMPLETION_SESSION')
def catalog(parent):
    own.parent_contract(parent);value=terms()
    for term in value:
        roles=[dict(slot_id=e['slot_id'],ticker=e['ticker'],quantity=e['current_shares'],entry_date=e['entry_date'])
            for _,e in sorted(parent['run']['state']['wealth_core']['episodes'].items(),key=lambda x:int(x[0])) if e['security_id']==term['security_id']]
        need(roles==term['parent_positions']==[],'P05_REMAINING18_ACTUAL_FULL_PARENT_ROLE_FOR_EVERY_MEMBER')
    return dict(schema='research.P05-own1175-retained18-source-stock-cash-catalog/1',arm='P05',root_admission_sha256=own.ROOT,
        parent_outer_sha256=own.OUTER,parent_cursor='2022-08-31',full_parent_inputs=19,terms=value,
        source331_qualification_sha256=own.PINS['P05-CTX-source-qualification-v1.json'],reuse_qualifications=dict(PINS),
        canonical_financial_source_changed=False,historical_causality='UNVERIFIED')
def codec(parent):
    value=catalog(parent)
    return SimpleNamespace(catalog=value,catalog_sha=sha(encoded(value)),compiler_sha=sha(Path(__file__).read_bytes()),
        validator_description='Bounded eighteen exact original source-only/cash/stock records with fresh SOURCE331 identities; original policies, delivery/CIL and dynamic actual-ownership guards retained.')
def validate_provider(path):
    raw=Path(path).read_bytes()
    need(len(raw)==9855560 and sha(raw)=='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02',
        'P05_REMAINING18_ENTIRE_ORIGINAL_PROVIDER_OBJECT_BEFORE_PARSE')
    sr,_=records();rows={v['original_term']['ticker']:[] for v in sr['terms']}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            with z.open(name) as s,io.TextIOWrapper(s,encoding='utf8',newline='') as text:
                for row in csv.DictReader(text):
                    for v in sr['terms']:
                        term=v['original_term']
                        if row['date']==term['native_session'] and term['ticker'] in (row['ticker'],row['contraticker']):rows[term['ticker']].append(row)
    for v in sr['terms']:stock.require_provider_rows(rows[v['original_term']['ticker']],v['original_term'])
    return dict(passed=True,provider_sha256=sha(raw),original_provider_rows_verified=sum(map(len,rows.values())),financial_sessions_advanced=0)
