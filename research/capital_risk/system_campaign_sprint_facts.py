"""Source-bound Sprint alias/stock consideration; no metadata authority upgrade."""
import csv
from dataclasses import asdict
from fractions import Fraction
import io
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import urllib.request
import zipfile

from full_system_benchmark import need,save
from system_campaign_facts import digest,sha

CATALOG='research:system-optimization-002/sprint-terminal-catalog/1'
COMPILER='research:system-optimization-002/sprint-terminal-compiler/1'
HYDRATED='research:system-optimization-002/sprint-private-terminal-catalog/1'
SID='957008674074369745'
ALIAS_SHA='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
ALIAS_BYTES=9855560
ALIAS_URL='https://raw.githubusercontent.com/flabber1835/stocker/86fe82c474396ce84c91e8b774ae97a4500f7b39/sharadar/SHARADAR_ACTIONS.zip'


def alias_rows(path,expected):
    raw=path.read_bytes()
    need(len(raw)==ALIAS_BYTES and sha(raw)==ALIAS_SHA,'SPRINT_ORIGINAL_FROZEN_PROVIDER_SOURCE_BEFORE_PARSE')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name,=[n for n in archive.namelist() if n.lower().endswith('.csv')]
        text=archive.read(name).decode('utf-8-sig');first=text.splitlines()[0]
        reader=csv.DictReader(io.StringIO(text),delimiter='\t' if first.count('\t')>=first.count(',') else ',')
        rows=[r for r in reader if r['date']=='2020-03-31' and r['ticker']=='S2']
    need(len(rows)==4 and sorted(digest(r) for r in rows)==expected,'SPRINT_EXACT_FOUR_ORIGINAL_ALIAS_ROWS')
    need(all(r['name']=='SPRINT CORP' for r in rows)
         and any(r['action']=='tickerchangefrom' and r['contraticker']=='S' for r in rows)
         and any(r['action']=='acquisitionby' and r['contraticker']=='TMUS' and r['contraname']=='T-MOBILE US INC' for r in rows),
         'SPRINT_CAUSAL_PROVIDER_ALIAS_AND_COUNTERPARTY')
    return rows


def fetch_alias(out):
    need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
         and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','SPRINT_PUBLIC_SOURCE_HOSTED_ORCHESTRATOR_ONLY')
    folder=out/'provider-source';folder.mkdir();target=folder/'SHARADAR_ACTIONS.zip'
    count=0
    with urllib.request.urlopen(ALIAS_URL,timeout=45) as source,target.open('xb') as dest:
        while raw:=source.read(1024**2):
            count+=len(raw);need(count<=ALIAS_BYTES,'SPRINT_BOUNDED_ORIGINAL_PROVIDER_DOWNLOAD');dest.write(raw)
    catalog=json.loads(Path('/driver/system-campaign-sprint-terminal-facts.json').read_bytes()) if Path('/driver').is_dir() else json.loads((Path(__file__).parent/'system-campaign-sprint-terminal-facts.json').read_bytes())
    rows=alias_rows(target,catalog['provider_alias_source']['selected_row_sha256'])
    save(out/'provider-alias-proof.json',dict(source_sha256=ALIAS_SHA,source_bytes=count,selected_rows=rows,
        descriptive_fields_used_only_for_action_identity=True,strategy_metadata_upgraded=False))


class SprintFacts:
    def __init__(self,path):
        self.raw=Path(path).read_bytes();self.catalog=json.loads(self.raw);c=self.catalog;a=c['added']
        need(c['schema']=='research.system-campaign-sprint-terminal-facts/1'
             and not any(c[k] for k in ('provider_snapshot_used_as_strategy_metadata','canonical_financial_source_changed','production_contacted')),
             'SPRINT_FACTUAL_ONLY_SCOPE')
        need(c['native_session']=='2020-03-31' and a['session']=='2020-04-01' and a['security_id']==SID
             and a['kind']=='CONVERSION' and a['exchange_ratio']=='0.10256' and a['cash_per_share'] is None
             and a['cash_in_lieu_price_per_delivered_share'] is None and a['entitlement_aggregation']=='HOLDER'
             and (a['delivered_security_id'],a['delivered_ticker'],a['delivered_issuer_id'])==('36692955301160544','TMUS','SEC_CIK:1283699'),
             'SPRINT_EXACT_PUBLIC_COMMON_HOLDER_STOCK_CONSIDERATION')
        w=c['source_identity_witness'];d=c['delivered_identity_witness']
        need((w['session'],w['security_id'],w['ticker'],w['issuer_id'],w['listing_first_session'],w['security_type_eligible'])==
             ('2020-03-30',SID,'S2','SEC_UNKNOWN:'+SID,'1997-12-31','0')
             and (d['session'],d['security_id'],d['ticker'],d['issuer_id'],d['listing_first_session'],d['security_type_eligible'])==
             ('2020-04-01','36692955301160544','TMUS','SEC_CIK:1283699','2007-04-19','1'),
             'SPRINT_FROZEN_IDENTITIES_AND_INELIGIBILITY_UNCHANGED')
        p=c['provider_alias_source']
        need(p['url']==ALIAS_URL and p['sha256']==ALIAS_SHA and p['bytes']==ALIAS_BYTES
             and len(p['selected_row_sha256'])==4
             and c['cil_convention']=='FROZEN_DELIVERED_RAW_OPEN_PROXY_NOT_ISSUER_SETTLEMENT_PRICE',
             'SPRINT_EXACT_ORIGINAL_PROVIDER_SOURCE_AND_DECLARED_CIL_LIMITATION')
        self.catalog_sha=sha(self.raw);self.compiler_sha=sha(Path(__file__).read_bytes());self.hydrated_sha=None

    def hydrate(self,out,root):
        need(os.environ.get('FULL_SYSTEM_HOSTED')=='1' and Path('/variant').is_dir()
             and str(Path(__file__).resolve()).startswith('/driver/'),'HOSTED_SPRINT_FACTS_ONLY')
        from research.pooled_input_support import inputs
        c=self.catalog;alias_rows(root/'provider-source/SHARADAR_ACTIONS.zip',c['provider_alias_source']['selected_row_sha256'])
        actions=inputs.load_actions(Path('/frozen/bundle'))
        native,=[t for t in actions.terminal.get(c['native_session'],()) if t.security_id==SID]
        need(digest(asdict(native))==c['native_term_sha256'] and native.cash_per_share is None
             and not native.completeness(0)[0],'SPRINT_ACTUAL_INCOMPLETE_NATIVE_BEFORE_REPAIR')
        need(not any(t.security_id==SID for t in actions.terminal.get('2020-04-01',())),'SPRINT_NO_CONFLICTING_COMPLETE_ACTION')
        wanted={(w['session'],w['security_id']):w for w in (c['source_identity_witness'],c['delivered_identity_witness'])};seen={}
        with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
            for row in inputs._archive_rows(archive,'observations-2020.csv.gz'):
                key=row['session'],row['security_id']
                if key not in wanted:continue
                w=wanted[key];need(key not in seen and digest(row)==w['source_observation_sha256']
                    and all(row[k]==v for k,v in w.items() if k!='source_observation_sha256'),'SPRINT_EXACT_PRIVATE_SOURCE_AND_DELIVERED_WITNESSES')
                seen[key]=row
        need(set(seen)==set(wanted),'SPRINT_BOTH_FROZEN_WITNESSES_REQUIRED')
        self.delivered=seen[('2020-04-01','36692955301160544')]
        price=float(self.delivered['raw_open']);need(math.isfinite(price) and price>0,'SPRINT_POSITIVE_FROZEN_DECLARED_CIL_PROXY')
        c['added']['cash_in_lieu_price_per_delivered_share']=price
        save(out,c);self.hydrated_sha=sha(out.read_bytes());self.hydrated_digest=digest(c)

    def overlay(self,cp,out):
        need(self.hydrated_sha is not None and digest(self.catalog)==self.hydrated_digest,'SPRINT_HYDRATED_FACTS_IMMUTABLE')
        need(cp['source_cursor']<'2020-03-31','SPRINT_BOTH_EVENT_DATES_UNCONSUMED')
        c=self.catalog
        refs=[dict(reference=r,description=d,sha256=h) for r,d,h in (
            (CATALOG,'Exact Sprint ordinary-holder stock ratio/date/provider-alias and preserved unknown classification.',self.catalog_sha),
            (COMPILER,'Exact ordinary factual compiler; financial source and metadata authority unchanged.',self.compiler_sha),
            (HYDRATED,'Actual pinned original alias source and frozen delivered quote/CIL proxy.',self.hydrated_sha))]
        save(out,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],source_evidence=[*refs,
            dict(reference=c['primary_source'],description=c['added']['reference'],sha256=None),
            dict(reference=c['acquirer_source'],description='Acquirer confirms April1 completed merger; ordinary-holder ratio0.10256.',sha256=None)],
            suppress=[dict(session='2020-03-31',security_id=SID,term_sha256=c['native_term_sha256'])],add=[c['added']]))
        from research.pooled_vacancy_funding.repair import load_repair
        return load_repair(out,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])

    def qualify(self,loaded,out):
        from research.pooled_input_support import inputs
        from research.pooled_input_support.adapter import Packet
        from research.bounded_20y.run import vendor
        from research.pooled_vacancy_funding import backtest
        from sentinel.controller import terminal_returns
        actions=inputs.load_actions(Path('/frozen/bundle'));bar=vendor(self.delivered)
        for day in ('2020-03-31','2020-04-01'):
            original=Packet(day,(bar,) if day=='2020-04-01' else (),{},{},1.,{},tuple(actions.terminal.get(day,())),());before=digest(asdict(original))
            fixed=backtest.apply_repair(original,loaded)
            need(digest(asdict(original))==before,'SPRINT_ORIGINAL_PACKET_UNCHANGED')
            terms=[t for t in fixed.terminal if t.security_id==SID]
            if day=='2020-03-31':need(not terms,'SPRINT_PRESERVE_MARCH31_TRADING');old=original
            else:
                need(len(terms)==1 and asdict(terms[0])==self.catalog['added'] and terms[0].completeness(1)[0],
                     'SPRINT_COMPLETE_ORDINARY_HOLDER_CONVERSION');new=fixed
        def prior(day):return SimpleNamespace(median5={'selected':[SID]},feed={'series':{SID:{'signal_basis_anchor':(day,1.,1.)}}},last_processed_session=day)
        def published(packet):return SimpleNamespace(session=packet.session,bars=packet.bars,terminal_events=packet.terminal)
        try:terminal_returns.values(prior=prior('2020-03-30'),published=published(old))
        except ValueError as error:need('incomplete leadership cash terminal' in str(error),'SPRINT_ORIGINAL_INCOMPLETE_GUARD_REASON')
        else:raise ValueError('SPRINT_ORIGINAL_INCOMPLETE_GUARD_MISSING')
        value=terminal_returns.values(prior=prior('2020-03-31'),published=published(new))
        need(value[SID]==float(Fraction('0.10256')*Fraction(str(bar.raw_close))),'SPRINT_ACTUAL_CANONICAL_NOTIONAL_STOCK_CONSIDERATION')
        bad=SimpleNamespace(session='2020-04-01',bars=(),terminal_events=new.terminal)
        try:terminal_returns.values(prior=prior('2020-03-31'),published=bad)
        except ValueError as error:need('lacks delivered close' in str(error),'SPRINT_MISSING_QUOTE_GUARD_REASON')
        else:raise ValueError('SPRINT_MISSING_DELIVERED_QUOTE_GUARD_MISSING')
        save(out,dict(actual_native_and_added_packet_checks=2,original_packets_unchanged=True,
            actual_canonical_notional_conversion_verified=True,original_incomplete_guard_retained=True,missing_delivered_quote_refused=True,
            source_unknown_issuer_and_ineligible_preserved=True,ratio='0.10256',last_trading_session='2020-03-31',effective_preopen_session='2020-04-01',
            cil_convention=self.catalog['cil_convention'],catalog_sha256=self.catalog_sha,compiler_sha256=self.compiler_sha,
            private_hydrated_sha256=self.hydrated_sha,financial_sessions_advanced=0))


def preserve_prior_facts(cp,old,out):
    from system_campaign_medicines_facts import CATALOG as MC,COMPILER as MP,HYDRATED as MH
    from system_campaign_arqule_facts import CATALOG as AC,COMPILER as AP,HYDRATED as AH
    proofs={}
    for stem,refs in (('medicines',(MC,MP,MH)),('arqule',(AC,AP,AH))):
        name='hydrated-'+stem+'-terminal-catalog.json'
        expected={refs[0]:sha((Path('/driver')/('system-campaign-'+stem+'-terminal-facts.json')).read_bytes()),
            refs[1]:sha((Path('/driver')/('system_campaign_'+stem+'_facts.py')).read_bytes()),refs[2]:sha((old/name).read_bytes())}
        found=[]
        for descriptor in cp['repairs']:
            raw=(old/'book/repairs'/descriptor['filename']).read_bytes();need(sha(raw)==descriptor['sha256'],'SPRINT_ALL_RETAINED_INPUT_BYTES')
            found.extend(v for v in json.loads(raw)['source_evidence'] if v['reference'] in expected)
        need(len(found)==3 and {v['reference']:v['sha256'] for v in found}==expected,'SPRINT_EXACT_RETAINED_'+stem.upper()+'_FACTUAL_COMMITMENTS')
        with (out/name).open('xb') as stream:stream.write((old/name).read_bytes())
        need(sha((out/name).read_bytes())==expected[refs[2]],'SPRINT_RETAINED_PRIVATE_BYTES_UNCHANGED');proofs[stem]=expected
    save(out/'retained-prior-facts-proof.json',dict(source_evidence=proofs,retained_bytes_unchanged=True,old_overlay_reapplied_as_new=False,financial_sessions_advanced=0))
