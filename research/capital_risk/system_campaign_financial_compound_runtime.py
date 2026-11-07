"""Hosted input projection and delegating observations for an admitted compound input.

The selected catalog must pin CLOSED source/DATA evidence before any preparation.
Financial transitions, input adoption, source primitives and accounting stay with
the original canonical implementations.
"""
from contextlib import contextmanager, nullcontext, ExitStack
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import gzip
import inspect
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import digest, sha
from system_campaign_financial_compound_input import build_terms, actual_role, EventSessionProjection

HERE = Path(__file__).parent
CATALOG_FILE = 'system-campaign-compound-input-facts.json'
# Root replaces this only after source231 and independent DATA are closed.
CATALOG_SHA = '90b60f312a64f5a24bf30cec678feb6a85dbecd9228dadfaa98928b6bf3f5bff'
SOURCE_V1 = 'system_campaign_financial_distribution_source_v1.py'
SOURCE_V1_SHA = 'b7270b94ac02db3d1090c9fc9e799ebe8046c1c74dc4787a972228564a82856f'
PAYLOAD = 'hydrated-compound-input.json'
OVERLAY = 'future-financial-overlay.json'
QUALIFICATION = 'compound-input-qualification.json'
ACTUAL = 'actual-compound-event.json'
CATALOG_REF = 'research.compound-distribution-terminal/catalog/1'
COMPILER_REF = 'research.compound-distribution-terminal/compiler/1'
MODEL_REF = 'research.compound-distribution-terminal/model/1'
PAYLOAD_REF = 'research.compound-distribution-terminal/payload/1'
SOURCE_REF = 'research.compound-distribution-terminal/closed-source-producer/1'
DATA_REF = 'research.compound-distribution-terminal/source-DATA/1'
ORIGINAL_COMPILER_REF = 'research.compound-distribution-terminal/original-distribution-compiler/1'


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def hash_value(value):
    return type(value) is str and len(value) == 64 and set(value) <= set('0123456789abcdef') and value != '0' * 64


def descriptor():
    return json.loads((HERE / CATALOG_FILE).read_bytes())


def applies(cp, arm):
    # This selects a phase only. qualified_record is mandatory before activation.
    return any((r['arm'], r['parent_cursor'], r['parent_outer_sha256'])
               == (arm, cp['source_cursor'], cp['sha256']) for r in descriptor()['records'])


def qualified_record(arm=None):
    raw = (HERE / CATALOG_FILE).read_bytes()
    need(hash_value(CATALOG_SHA) and sha(raw) == CATALOG_SHA, 'COMPOUND_CLOSED_SELECTED_CATALOG_PIN_REQUIRED')
    catalog = json.loads(raw)
    need(catalog['schema'] == 'research.selected-compound-distribution-terminal/1'
         and catalog['canonical_financial_source_changed'] is catalog['production_contacted'] is False,
         'COMPOUND_SELECTED_INPUT_ONLY_CATALOG')
    records = [r for r in catalog['records'] if arm is None or r['arm'] == arm]
    need(len(records) == 1, 'COMPOUND_ONE_EXACT_SELECTED_RECORD')
    r, = records;proof = r['source_proof']
    need(r['status'] == 'CLOSED_SOURCE_DATA_QUALIFIED_INPUT'
         and isinstance(proof, dict) and proof['independent_DATA_passed'] is True
         and proof['independent_qualification_passed'] is True
         and type(proof['run_id']) is int and proof['run_id'] > 0
         and type(proof['artifact_id']) is int and proof['artifact_id'] > 0
         and type(proof['head']) is str and len(proof['head']) == 40
         and all(hash_value(proof[k]) for k in ('zip_sha256','payload_sha256','payload_digest',
             'producer_sha256','independent_data_review_sha256','independent_qualification_sha256','scope_sha256'))
         and proof['distribution_producer_sha256'] == SOURCE_V1_SHA
         and proof['scope_sha256'] == digest(r['source_scope'])
         and r['source_scope']['parent_outer_sha256'] == r['parent_outer_sha256']
         and r['source_scope']['parent_cursor'] == r['parent_cursor']
         and all(hash_value(r[k]) for k in ('parent_root_admission_sha256','parent_outer_sha256',
             'parent_inner_sha256','parent_input_sha256','source_bindings_sha256')),
         'COMPOUND_CLOSED_SOURCE_DATA_ALL_PROVENANCE_PINS_REQUIRED')
    need(sha((HERE / SOURCE_V1).read_bytes()) == SOURCE_V1_SHA,
         'COMPOUND_IMMUTABLE_ORIGINAL_SOURCE_PRODUCER')
    return r


def source_parent(r):
    from system_campaign_financial_partial import root_spec
    s = root_spec(r['arm'], r['parent_root_admission_sha256'])
    need((s['outer_sha256'],s['inner_sha256'],s['input_sha256'],s['selected_session'])
         == (r['parent_outer_sha256'],r['parent_inner_sha256'],r['parent_input_sha256'],r['parent_cursor']),
         'COMPOUND_SEPARATE_OWN_ADMITTED_ORIGINAL_PARENT')
    return s


def reconstruct_source(r, spec):
    """Rebuild the exact old receipt using its immutable old producer, not v7."""
    hosted()
    import system_campaign_financial_distribution_source_v1 as original
    from research.pooled_input_support import inputs
    from research.bounded_20y import run
    need(sha(Path(original.__file__).read_bytes()) == SOURCE_V1_SHA
         and sha(Path(run.__file__).read_bytes()) == original.PARSER_SHA,
         'COMPOUND_ORIGINAL_SOURCE_PRODUCER_AND_PARSER_BYTES')
    scope = r['source_scope'];term, query = original.validate_scope(scope)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native = [asdict(t) for t in actions.terminal.get(term['native_session'],()) if t.security_id == term['security_id']]
    keys = {(term['session'],term['security_id'])}
    extras = {(w['session'],w['security_id']) for w in scope['additional_rows']}
    rows = [];source = [];all_spins = None
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        raw = archive.read('actions.csv.gz')
        need(len(raw) == original.ACTIONS_BYTES and sha(raw) == original.ACTIONS_SHA,
             'COMPOUND_EXACT_FROZEN_ACTIONS_MEMBER')
        raw_actions = list(inputs._archive_rows(archive,'actions.csv.gz'))
        all_spins = run.distributions(raw_actions)
        source = [v for v in raw_actions if v['effective_session'] == query['session']
                  and v['security_id'] == query['parent_security_id'] and v['action'].lower() in ('spinoff','spinoffdividend')]
        for year in sorted({d[:4] for d,_ in keys | extras}):
            rows.extend(v for v in inputs._archive_rows(archive,'observations-'+year+'.csv.gz')
                        if (v['session'],v['security_id']) in keys | extras)
    need(len(source) == 1, 'COMPOUND_NO_UNQUALIFIED_EXTRA_NATIVE_DISTRIBUTION')
    typed = [v for v in all_spins.get(query['session'],()) if v.parent_security_id == query['parent_security_id']]
    need(len(typed) == 1, 'COMPOUND_ONE_ORIGINAL_TYPED_DISTRIBUTION')
    positions = {v['security_id']: deepcopy(v['parent_positions']) for v in [term,*scope['additional_rows']]}
    data = original.material(scope,native,[v for v in rows if (v['session'],v['security_id']) in keys],
        [v for v in rows if (v['session'],v['security_id']) in extras],[(source[0],asdict(typed[0]))],positions)
    value = original.payload(spec,scope,data,r['source_proof']['producer_sha256'])
    original.validate(value,spec,scope,r['source_proof']['producer_sha256'])
    need(sha(encoded(value)) == r['source_proof']['payload_sha256']
         and digest(value) == r['source_proof']['payload_digest'], 'COMPOUND_EXACT_CLOSED_SOURCE_RECEIPT_REPRODUCED')
    return value, actions, all_spins


def refs(payload_raw, r):
    return {CATALOG_REF: CATALOG_SHA,COMPILER_REF:sha(Path(__file__).read_bytes()),
        MODEL_REF:sha((HERE/'system_campaign_financial_compound_input.py').read_bytes()),
        SOURCE_REF:SOURCE_V1_SHA,DATA_REF:r['source_proof']['independent_data_review_sha256'],
        ORIGINAL_COMPILER_REF:sha((HERE/'system_campaign_distribution_facts.py').read_bytes()),
        PAYLOAD_REF:sha(payload_raw)}


def hydrate(cp, arm):
    r = qualified_record(arm);s = source_parent(r)
    need(cp['sha256'] == s['outer_sha256'] and cp['source_cursor'] == s['selected_session']
         and cp['run']['checkpoint_sha256'] == s['inner_sha256'] and cp['run']['input_sha256'] == s['input_sha256']
         and cp['base'] == s['base'], 'COMPOUND_INITIAL_EXACT_OWN_ROOT_AND_GENERATION')
    source,actions,spins = reconstruct_source(r,s)
    binding = build_terms(r['research_assumption'],source,child_security_id=r['child_security_id'],
        delivered_security_id=r['delivered_security_id'],reference=r['reference'])
    actual_role(cp['run']['state'],cp['run']['state']['pending'],binding)
    return dict(schema='research.hydrated-compound-distribution-terminal/1',record_sha256=digest(r),
        source_payload=source,binding=binding,base=deepcopy(cp['base']),
        original_parent=dict(outer_sha256=cp['sha256'],inner_sha256=cp['run']['checkpoint_sha256'],
            input_sha256=cp['run']['input_sha256'],cursor=cp['source_cursor']),
        financial_state_changed=False,production_contacted=False),actions,spins


def document(payload, raw):
    r = qualified_record();b = payload['binding']
    return dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=payload['original_parent']['inner_sha256'],
        source_evidence=[dict(reference=k,description='Qualified own compound research input; original financial engine unchanged.',sha256=v)
                         for k,v in sorted(refs(raw,r).items())],
        suppress=[dict(session=b['original_terminal']['session'],security_id=b['original_terminal']['security_id'],
                       term_sha256=digest(b['original_terminal']))],add=[deepcopy(b['terminal'])])


def verify_payload(root):
    hosted();r = qualified_record();s = source_parent(r)
    raw = (Path(root)/PAYLOAD).read_bytes();p = json.loads(raw)
    source,_,_ = reconstruct_source(r,s)
    binding = build_terms(r['research_assumption'],source,child_security_id=r['child_security_id'],
        delivered_security_id=r['delivered_security_id'],reference=r['reference'])
    expected = dict(schema='research.hydrated-compound-distribution-terminal/1',record_sha256=digest(r),
        source_payload=source,binding=binding,base=s['base'],original_parent=dict(outer_sha256=s['outer_sha256'],
            inner_sha256=s['inner_sha256'],input_sha256=s['input_sha256'],cursor=s['selected_session']),
        financial_state_changed=False,production_contacted=False)
    need(p == expected, 'COMPOUND_COMPLETE_INDEPENDENT_SOURCE_INPUT_RECONSTRUCTION')
    return p,raw


class ProjectionContext:
    """Apply only after the exact activated ordinary document; all other loaders delegate."""
    def __init__(self, root, overlay=OVERLAY, *, payload=None, api=None):
        self.root=Path(root);self.overlay=self.root/overlay
        self.payload,self.raw=verify_payload(root) if payload is None else payload
        self.document=json.loads(self.overlay.read_bytes());self.overlay_sha=sha(self.overlay.read_bytes())
        need(self.document == document(self.payload,self.raw), 'COMPOUND_EXACT_ACTIVATED_ORDINARY_OVERLAY')
        self.api=api;self.active=False;self.bound_objects=[];self.changed_packets=0

    def __enter__(self):
        hosted()
        if self.api is None:
            from research.pooled_vacancy_funding import backtest,repair
            from research.bounded_20y.run import vendor
            from sentinel.core.spinoffs import SpinoffDistribution
            self.api=SimpleNamespace(backtest=backtest,repair=repair,vendor=vendor,spin_factory=SpinoffDistribution)
        a=self.api;b=self.payload['binding'];rows=b['original_rows']
        self.projection=EventSessionProjection(b,parent_bar=a.vendor(rows[b['spin']['parent_security_id']]),
            child_bar=a.vendor(rows[b['spin']['child_security_id']]),source_raw=Path(a.repair.__file__).read_bytes(),
            source_namespace=vars(a.repair),spin_factory=a.spin_factory)
        self.original_load=a.backtest.load_repair;self.original_apply=a.backtest.apply_repair
        a.backtest.load_repair=self.load;a.backtest.apply_repair=self.apply;self.active=True
        return self

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        obj=self.original_load(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        rows=[e for e in obj.source_evidence if e.reference==CATALOG_REF]
        if rows:
            need(len(rows)==1 and sha(Path(path).read_bytes())==self.overlay_sha
                 and Path(path).read_bytes()==self.overlay.read_bytes()
                 and resume_session==self.payload['original_parent']['cursor']
                 and predecessor_checkpoint_sha256==self.payload['original_parent']['inner_sha256'],
                 'COMPOUND_LOADER_ONLY_EXACT_ACTIVATION_PARENT_AND_BYTES')
            self.bound_objects.append(obj)
        return obj

    def apply(self,packet,obj):
        fixed=self.original_apply(packet,obj)
        refs_=[e for e in obj.source_evidence if e.reference==CATALOG_REF]
        if not refs_:return fixed
        need(any(obj is v for v in self.bound_objects) and obj.sha256==self.overlay_sha,
             'COMPOUND_APPLY_REQUIRES_ACTUAL_QUALIFIED_LOADER_OBJECT')
        result=self.projection.apply(fixed,self.projection.descriptor)
        if result != fixed:self.changed_packets+=1
        return result

    def __exit__(self,*args):
        self.api.backtest.load_repair=self.original_load;self.api.backtest.apply_repair=self.original_apply;self.active=False


def original_role(binding,before):
    return sum((Fraction(str(e['current_shares'])) for e in before['episodes'].values()
                if e['security_id']==binding['spin']['parent_security_id']),Fraction(0))


def consideration(binding, quantity, cost_bps):
    spin,term=binding['spin'],binding['terminal'];child=Fraction(spin['child_shares_per_parent'])*quantity
    whole=child.numerator//child.denominator;fraction=child-whole;px=Fraction(spin['cash_in_lieu_price'])
    whole_proceeds=float(whole*px*(1-Fraction(str(cost_bps))/10000));cil=float(fraction*px)
    delivery=quantity*Fraction(str(term['exchange_ratio']));dw=delivery.numerator//delivery.denominator
    need(dw==0, 'COMPOUND_OBSERVER_NO_CONTINUING_STOCK')
    cash=quantity*Fraction(str(term['cash_per_share']));stock_cil=delivery*Fraction(str(term['cash_in_lieu_price_per_delivered_share']))
    return dict(child_entitlement=str(child),child_whole=whole,child_fraction=str(fraction),
        child_whole_proceeds=whole_proceeds,child_fractional_cash=cil,child_cash=whole_proceeds+cil,
        delivered_entitlement=str(delivery),delivered_whole=dw,cash_leg=float(cash),stock_cil=float(stock_cil),
        terminal_cash=float(cash+stock_cil),exact_total_inflow=str(whole*px*(1-Fraction(str(cost_bps))/10000)+fraction*px+cash+stock_cil))


def spin_postcondition(binding,before,after,ledger_before,ledger_after,result,cost_bps):
    p=consideration(binding,original_role(binding,before),cost_bps);s=binding['spin']
    events=ledger_after['events'][len(ledger_before['events']):]
    need(ledger_after['events'][:len(ledger_before['events'])]==ledger_before['events']
         and len(events)==2 and [e['event_type'] for e in events]==['SPINOFF_RECEIPT','SPINOFF_LIQUIDATION']
         and all(e['security_id']==s['child_security_id'] and e['session']==s['session'] for e in events)
         and events[0]['shares_delta']==p['child_whole'] and events[1]['shares_delta']==-p['child_whole']
         and events[0]['detail']['fractional_entitlement']==p['child_fraction']
         and events[0]['cash_before']==before['cash'] and events[0]['cash_after']==before['cash']
         and events[1]['cash_before']==before['cash'] and events[1]['cash_delta']==p['child_cash']
         and events[1]['cash_after']==after['cash']
         and events[1]['price']==float(s['cash_in_lieu_price'])
         and events[1]['fees']==p['child_whole']*float(s['cash_in_lieu_price'])-p['child_whole_proceeds']
         and after['cash']==before['cash']+p['child_cash']
         and ledger_before.get('receivables',[])==ledger_after.get('receivables',[])
         and before['slots']==after['slots'], 'COMPOUND_EXACT_CANONICAL_CHILD_RECEIPT_SALE_FRACTION_CASH')
    need(len(result)==1 and result[0]['parent_security_id']==s['parent_security_id']
         and result[0]['child_security_id']==s['child_security_id']
         and result[0]['whole_child_shares']==p['child_whole'] and result[0]['fractional_child_shares']==p['child_fraction']
         and result[0]['cash_proceeds']==p['child_cash'], 'COMPOUND_EXACT_CANONICAL_CHILD_AUDIT')
    parent=s['parent_security_id']
    need({k:v for k,v in before['episodes'].items() if v['security_id']!=parent}
         == {k:v for k,v in after['episodes'].items() if v['security_id']!=parent}
         and original_role(binding,before)==original_role(binding,after), 'COMPOUND_CHILD_SALE_PRESERVES_PARENT_UNITS_AND_OTHER_EPISODES')
    parent_open=float(binding['original_rows'][parent]['raw_open'])
    child_open=float(s['cash_in_lieu_price'])
    scale=parent_open/(parent_open+float(Fraction(s['child_shares_per_parent'])*Fraction(str(child_open))))
    for key,old in before['episodes'].items():
        if old['security_id']!=parent:continue
        expected=deepcopy(old);expected['entry_split_adjusted_price']*=scale
        if expected['episode_peak_split_adjusted_close'] is not None:expected['episode_peak_split_adjusted_close']*=scale
        expected['source_lots']=list(expected['source_lots'])+[dict(kind='SPINOFF_CHILD_LIQUIDATION',session=s['session'],
            source_row_id=s['source_row_id'],parent_security_id=parent,child_security_id=s['child_security_id'],
            child_ticker=s['child_ticker'],child_shares_per_parent=str(Fraction(s['child_shares_per_parent'])),
            child_open=child_open,reference_scale=scale)]
        need(after['episodes'][key]==expected, 'COMPOUND_EXACT_ORIGINAL_CANONICAL_PARENT_REFERENCE_REBASE_AND_LOT')
    return p


def terminal_postcondition(binding,before,after,ledger_before,ledger_after,result):
    p=consideration(binding,original_role(binding,before),10);t=binding['terminal'];sid=t['security_id']
    events=ledger_after['events'][len(ledger_before['events']):]
    need(result.get('applied') is True and result.get('converted') is False
         and result['cash_consideration']==p['cash_leg'] and result['cash_in_lieu']==p['stock_cil']
         and after['cash']==before['cash']+p['terminal_cash']
         and len(events)==1 and events[0]['event_type']=='CONVERSION'
         and events[0]['security_id']==sid and events[0]['shares_delta']==-float(original_role(binding,before))
         and events[0]['cash_before']==before['cash'] and events[0]['cash_after']==after['cash']
         and events[0]['cash_delta']==after['cash']-before['cash']
         and events[0]['detail']['exact_fractional_entitlement']==p['delivered_entitlement']
         and events[0]['detail']['reference']==t['reference']
         and ledger_after['events'][:len(ledger_before['events'])]==ledger_before['events']
         and ledger_after.get('receivables',[])==ledger_before.get('receivables',[]),
         'COMPOUND_EXACT_CANONICAL_MIXED_CASH_FRACTION_LEDGER')
    ids={sid,t['delivered_security_id'],binding['spin']['child_security_id']}
    need(not any(e['security_id'] in ids for e in after['episodes'].values())
         and {k:v for k,v in before['episodes'].items() if v['security_id']!=sid}==after['episodes']
         and all(not any(i in after.get(k,{}) for i in ids) for k in ('terminal_pending_terms','terminal_pending_sessions','unresolved_terminals','terminal_carry_audit','last_valid_mark_session','sessions_since_valid_mark'))
         and all(v.get('occupied_by') not in ids and v.get('reserved_for') not in ids for v in after['slots'].values()),
         'COMPOUND_PARENT_RETIRED_WITH_NO_UNQUALIFIED_CHILD_DELIVERY_OR_CLAIM')
    return p


class Observer:
    def __init__(self,root,payload,*,api=None):
        self.root=Path(root);self.payload=payload;self.binding=payload['binding'];self.api=api;self.saved=[];self.current=None

    def patch(self,owner,name,fn):
        old=getattr(owner,name);self.saved.append((owner,name,old));setattr(owner,name,fn);return old

    def __enter__(self):
        hosted()
        if self.api is None:
            from research.pooled_vacancy_funding import runtime
            from sentinel.core import kernel,spinoffs
            from stock_strategy_shared.wealth_core import terminal,adapter
            from sentinel.controller import terminal_returns
            self.api=SimpleNamespace(runtime=runtime,kernel=kernel,spinoffs=spinoffs,terminal=terminal,adapter=adapter,terminal_returns=terminal_returns)
        a=self.api
        for owner,key in ((a.runtime,'research/pooled_vacancy_funding/runtime.py'),(a.kernel,'sentinel/core/kernel.py'),
            (a.spinoffs,'sentinel/core/spinoffs.py'),(a.terminal,'shared/stock_strategy_shared/wealth_core/terminal.py'),
            (a.adapter,'shared/stock_strategy_shared/wealth_core/adapter.py'),(a.terminal_returns,'sentinel/controller/terminal_returns.py')):
            need(sha(Path(owner.__file__).read_bytes())==self.payload['base']['sources'][key], 'COMPOUND_UNCHANGED_ACTUAL_FINANCIAL_SURFACE')
        self.kernel_code=a.kernel.advance_session.__code__;self.step_code=a.adapter.step_session.__code__
        self.advance_original=self.patch(a.runtime,'advance',self.advance)
        self.spin_original=self.patch(a.spinoffs,'apply_supported_entitlements',self.spin)
        self.terminal_original=self.patch(a.terminal,'apply_terminal',self.terminal)
        self.source_original=self.patch(a.terminal_returns,'values',self.source_values)
        return self

    def __exit__(self,*args):
        for owner,name,old in reversed(self.saved):setattr(owner,name,old)

    def advance(self,run,publication):
        if publication.session!=self.binding['terminal']['session']:return self.advance_original(run,publication)
        need(self.current is None, 'COMPOUND_SINGLE_ACTUAL_ADVANCE')
        self.current=dict(session=publication.session,order=[],spin=None,terminal=None,source_notional=None)
        try:
            actual_role(dict(wealth_core=run.state.wealth_core,ledger=run.state.ledger),run.state.pending,self.binding)
            result=self.advance_original(run,publication)
            need(self.current['order']==['SPINOFF','TERMINAL'] and self.current['spin'] is not None
                 and self.current['terminal'] is not None and self.current['source_notional'] is not None,
                 'COMPOUND_BOTH_CANONICAL_CALLS_IN_ORDER_BEFORE_COMMIT')
            save(self.root/ACTUAL,dict(self.current,passed=True,financial_source_changed=False))
            return result
        except BaseException as error:
            save(self.root/'compound-event-refusal.json',dict(self.current,passed=False,error=str(error),financial_source_changed=False))
            raise
        finally:self.current=None

    def spin(self,state,distributions,*,bars,ledger,config):
        selected=[v for v in distributions if v.source_row_id==self.binding['spin']['source_row_id']]
        if not selected:return self.spin_original(state,distributions,bars=bars,ledger=ledger,config=config)
        caller=inspect.currentframe().f_back
        need(self.current is not None and caller.f_code is self.kernel_code and len(selected)==1
             and asdict(selected[0])==self.binding['spin'], 'COMPOUND_ACTUAL_KERNEL_SPIN_CALL_ONLY')
        before=deepcopy(state.to_dict());lb=deepcopy(ledger.to_dict())
        pending=[v.to_dict() if hasattr(v,'to_dict') else asdict(v) for v in caller.f_locals['pending']]
        actual_role(dict(wealth_core=before,ledger=lb),pending,self.binding)
        result=self.spin_original(state,distributions,bars=bars,ledger=ledger,config=config)
        proof=spin_postcondition(self.binding,before,state.to_dict(),lb,ledger.to_dict(),result,config.transaction_cost_bps)
        self.current['spin']=proof;self.current['order'].append('SPINOFF');return result

    def terminal(self,state,terms,**kwargs):
        if terms.security_id!=self.binding['terminal']['security_id'] or terms.session!=self.binding['terminal']['session']:
            return self.terminal_original(state,terms,**kwargs)
        caller=inspect.currentframe().f_back
        need(self.current is not None and self.current['order']==['SPINOFF'] and caller.f_code is self.step_code
             and caller.f_locals.get('state') is state and caller.f_locals.get('ledger') is kwargs['ledger']
             and asdict(terms)==self.binding['terminal'] and kwargs.get('phase','OPEN')=='OPEN',
             'COMPOUND_ACTUAL_ADAPTER_MIXED_TERMINAL_AFTER_SPIN')
        before=deepcopy(state.to_dict());lb=deepcopy(kwargs['ledger'].to_dict())
        result=self.terminal_original(state,terms,**kwargs)
        self.current['terminal']=terminal_postcondition(self.binding,before,state.to_dict(),lb,kwargs['ledger'].to_dict(),result)
        self.current['order'].append('TERMINAL');return result

    def source_values(self,*,prior,published):
        if published.session!=self.binding['terminal']['session']:
            return self.source_original(prior=prior,published=published)
        caller=inspect.currentframe().f_back
        need(self.current is not None and caller.f_code is self.kernel_code
             and caller.f_locals.get('env') is prior and caller.f_locals.get('published') is published,
             'COMPOUND_ACTUAL_ORIGINAL_CONTROLLER_NOTIONAL_CALL')
        before=deepcopy((prior.wealth_core,prior.pending,prior.ledger))
        value=self.source_original(prior=prior,published=published)
        need(before==(prior.wealth_core,prior.pending,prior.ledger), 'COMPOUND_ORIGINAL_CONTROLLER_NOTIONAL_READONLY')
        t=self.binding['terminal'];sid=t['security_id']
        terms=[v for v in published.terminal_events if v.security_id==sid]
        bars=[v for v in published.bars if v.security_id==t['delivered_security_id']]
        need(len(terms)==len(bars)==1 and asdict(terms[0])==t,
             'COMPOUND_ACTUAL_CONTROLLER_INPUT_SAME_QUALIFIED_MIXED_TERM')
        consideration=Fraction(str(t['cash_per_share']))+Fraction(str(t['exchange_ratio']))*Fraction(str(bars[0].raw_close))
        selected=sid in prior.median5['selected']
        anchor=None
        parent_bars=[v for v in published.bars if v.security_id==sid]
        need(len(parent_bars)<=1, 'COMPOUND_ACTUAL_CONTROLLER_UNAMBIGUOUS_SOURCE_BAR')
        split=Fraction(str(parent_bars[0].split_ratio)) if parent_bars else Fraction(1)
        expected=consideration
        if selected:
            anchor=prior.feed['series'].get(sid,{}).get('signal_basis_anchor')
            need(anchor and anchor[0]==prior.last_processed_session and Fraction(str(anchor[1]))>0
                 and Fraction(str(anchor[2]))>0 and split>0, 'COMPOUND_ACTUAL_CONTROLLER_EXACT_PRIOR_PRICE_DOMAIN')
            expected*=split*Fraction(str(anchor[2]))/Fraction(str(anchor[1]))
        expected=float(expected)
        need(value.get(sid)==expected if selected else sid not in value,
             'COMPOUND_ACTUAL_ORIGINAL_CONTROLLER_MIXED_NOTIONAL')
        self.current['source_notional']=dict(actual_kernel_call=True,original_delegated=True,selected=selected,
            expected_notional=expected,returned_notional=value.get(sid),prior_signal_basis=deepcopy(anchor),source_split=str(split))
        return value


def retained_activation(root,cp):
    root=Path(root);found=[]
    for d in cp['repairs']:
        raw=(root/'book/repairs'/d['filename']).read_bytes()
        need(sha(raw)==d['sha256'], 'COMPOUND_EXACT_RETAINED_REPAIR_BYTES')
        if any(v['reference']==CATALOG_REF for v in json.loads(raw).get('source_evidence',[])):found.append(d)
    if not found:
        need(not (root/PAYLOAD).exists(), 'COMPOUND_NO_UNCOMMITTED_RETAINED_PAYLOAD');return None
    need(len(found)==1, 'COMPOUND_EXACTLY_ONE_RETAINED_ACTIVATION')
    d,=found;p,raw=verify_payload(root)
    r=qualified_record()
    need(cp['base']==p['base'] and cp['source_cursor']>=p['original_parent']['cursor']
         and d['resume_session']==p['original_parent']['cursor']
         and d['predecessor_checkpoint_sha256']==p['original_parent']['inner_sha256']
         and sha((root/'source-bindings.json').read_bytes())==r['source_bindings_sha256'],
         'COMPOUND_RETAINED_SAME_OWN_GENERATION_AND_ORIGINAL_ACTIVATION')
    return ProjectionContext(root,'book/repairs/'+d['filename'],payload=(p,raw))


@contextmanager
def retained_context(root,cp,out):
    projection=retained_activation(root,cp)
    if projection is None:
        yield;return
    raw=(Path(root)/PAYLOAD).read_bytes();target=Path(out)/PAYLOAD
    if target.exists():need(target.read_bytes()==raw, 'COMPOUND_RETAINED_HYDRATION_BYTE_EQUALITY')
    else:target.write_bytes(raw)
    with projection:yield


@contextmanager
def initial_context(cp,out,spec,loaded):
    from system_campaign_financial_resume import AdoptionGate
    with ExitStack() as stack:
        projection=stack.enter_context(ProjectionContext(out))
        stack.enter_context(AdoptionGate(cp,Path(out)/'book',Path(out)/'input-adoption',loaded.sha256,loaded.earliest_affected_session))
        stack.enter_context(Observer(out,projection.payload))
        yield


def prepare(cp,out,arm):
    hosted();p,actions,spins=hydrate(cp,arm);raw=encoded(p);save(Path(out)/PAYLOAD,p)
    path=Path(out)/OVERLAY;save(path,document(p,raw))
    from research.pooled_vacancy_funding.repair import load_repair
    loaded=load_repair(path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    qualify(cp,Path(out),p,actions,spins)
    return path,loaded


def review(cp,evidence,arm):
    hosted();p,_,_=hydrate(cp,arm);raw=encoded(p)
    need((Path(evidence)/PAYLOAD).read_bytes()==raw
         and json.loads((Path(evidence)/OVERLAY).read_bytes())==document(p,raw),
         'COMPOUND_INDEPENDENT_COMPLETE_INPUT_AND_OVERLAY_REVIEW')
    proof=json.loads((Path(evidence)/QUALIFICATION).read_bytes())
    need(proof['passed'] is True and proof['financial_sessions_advanced']==0
         and proof['source_payload_sha256']==sha(encoded(p['source_payload']))
         and proof['binding_sha256']==digest(p['binding']), 'COMPOUND_ORIGINAL_QUALIFICATION_REVIEW')
    current=json.loads(gzip.decompress((Path(evidence)/'book/checkpoint.json.gz').read_bytes()))
    actual=Path(evidence)/ACTUAL
    need(current['source_cursor'] < p['binding']['terminal']['session'] or actual.is_file(),
         'COMPOUND_POST_EVENT_CHECKPOINT_REQUIRES_ACTUAL_OBSERVER_PROOF')
    if actual.exists():
        value=json.loads(actual.read_bytes())
        expected=consideration(p['binding'],Fraction(str(p['binding']['parent_positions'][0]['quantity'])),10)
        need(value['passed'] is True and value['order']==['SPINOFF','TERMINAL']
             and value['session']==p['binding']['terminal']['session']
             and value['spin']==expected and value['terminal']==expected,
             'COMPOUND_ACTUAL_OBSERVER_ORDER_AND_RATIONAL_CONSIDERATION_REVIEW')
        source=value['source_notional'];t=p['binding']['terminal'];row=p['binding']['original_rows'][t['delivered_security_id']]
        notional=Fraction(str(t['cash_per_share']))+Fraction(str(t['exchange_ratio']))*Fraction(str(float(row['raw_close'])))
        if source['selected']:
            anchor=source['prior_signal_basis']
            need(anchor and Fraction(str(anchor[1]))>0 and Fraction(str(anchor[2]))>0,
                 'COMPOUND_REVIEW_EXPLICIT_CONTROLLER_PRICE_DOMAIN')
            notional*=Fraction(source['source_split'])*Fraction(str(anchor[2]))/Fraction(str(anchor[1]))
        notional=float(notional)
        need(source['actual_kernel_call'] is source['original_delegated'] is True
             and type(source['selected']) is bool and source['expected_notional']==notional
             and source['returned_notional']==(notional if source['selected'] else None),
             'COMPOUND_ACTUAL_ORIGINAL_CONTROLLER_NOTIONAL_REVIEW')
    return p['binding']['terminal']['session']


def qualify(cp,out,p,actions,spins):
    hosted()
    from research.pooled_vacancy_funding import backtest,repair
    from research.pooled_input_support.adapter import Packet
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.funding import config
    from stock_strategy_shared.wealth_core.terminal import apply_terminal
    from sentinel.core.spinoffs import apply_supported_entitlements
    from system_campaign_sprint_facts import published_packet,qualify_packet_schema
    qualify_packet_schema(Packet,cp['base']['sources']['research/pooled_input_support/adapter.py'])
    b=p['binding'];day=b['terminal']['session'];sid=b['terminal']['security_id'];fixed=None;recognition_packet=None
    with ProjectionContext(out) as ctx:
        loaded=backtest.load_repair(Path(out)/OVERLAY,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
        for date_ in (b['research_assumption']['actual_distribution_session'],day,b['original_native_distribution']['session']):
            bars=tuple(vendor(row) for row in b['original_rows'].values()) if date_==day else ()
            packet=Packet(date_,bars,{},{},1.,{},tuple(actions.terminal.get(date_,())),tuple(spins.get(date_,())))
            before=digest(asdict(packet));changed=backtest.apply_repair(packet,loaded)
            need(digest(asdict(packet))==before, 'COMPOUND_QUALIFICATION_ORIGINAL_PACKET_IMMUTABLE')
            if date_==day:fixed=changed;recognition_packet=packet
            elif date_==b['original_native_distribution']['session']:
                need(changed==replace(packet,spins=tuple(v for v in packet.spins if v.source_row_id!=b['spin']['source_row_id'])),
                     'COMPOUND_QUALIFICATION_ONLY_ORIGINAL_NATIVE_SPIN_REMOVED')
            else:need(changed==packet, 'COMPOUND_QUALIFICATION_OTHER_DATE_UNCHANGED')
        need(ctx.changed_packets==2, 'COMPOUND_BOTH_INPUT_BOUNDARIES_QUALIFIED')
    term,=[v for v in fixed.terminal if v.security_id==sid]
    need(asdict(term)==b['terminal'] and term.completeness(b['parent_positions'][0]['quantity'])[0], 'COMPOUND_COMPLETE_CANONICAL_MIXED_TERM')
    delivered=vendor(b['original_rows'][term.delivered_security_id])
    prior_day=p['source_payload']['terms'][0]['source_row']['session']
    prior=SimpleNamespace(median5={'selected':[sid]},feed={'series':{sid:{'signal_basis_anchor':(prior_day,1.,1.)}}},last_processed_session=prior_day)
    value=terminal_returns.values(prior=prior,published=published_packet(fixed))[sid]
    expected=float(Fraction(str(term.cash_per_share))+Fraction(str(term.exchange_ratio))*Fraction(str(delivered.raw_close)))
    need(value==expected, 'COMPOUND_ORIGINAL_CONTROLLER_MIXED_NOTIONAL')
    original_native=Packet(day,(),{},{},1.,{},tuple(actions.terminal.get(day,())),())
    try:terminal_returns.values(prior=prior,published=published_packet(original_native))
    except ValueError as error:need('incomplete leadership cash terminal' in str(error), 'COMPOUND_ORIGINAL_INCOMPLETE_CONTROLLER_GUARD_REASON')
    else:raise ValueError('COMPOUND_ORIGINAL_INCOMPLETE_CONTROLLER_GUARD_FALSIFIER')
    try:terminal_returns.values(prior=prior,published=published_packet(replace(fixed,bars=tuple(v for v in fixed.bars if v.security_id!=term.delivered_security_id))))
    except ValueError as error:need('lacks delivered close' in str(error), 'COMPOUND_ORIGINAL_MISSING_DELIVERY_GUARD_REASON')
    else:raise ValueError('COMPOUND_ORIGINAL_MISSING_DELIVERY_GUARD_FALSIFIER')
    bad=json.loads((Path(out)/OVERLAY).read_bytes());bad['suppress'][0]['term_sha256']='0'*64
    bad_path=Path(out)/'compound-wrong-native-falsifier.json';save(bad_path,bad)
    bad_loaded=repair.load_repair(bad_path,resume_session=cp['source_cursor'],predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    try:repair.apply_repair(recognition_packet,bad_loaded)
    except ValueError as error:need('suppressed original terminal differs' in str(error), 'COMPOUND_ORIGINAL_NATIVE_PARSER_GUARD_REASON')
    else:raise ValueError('COMPOUND_WRONG_NATIVE_PARSER_FALSIFIER')
    ordinary_fixed=repair.apply_repair(recognition_packet,loaded)
    bad_quote=replace(ordinary_fixed,bars=tuple(replace(v,raw_open=v.raw_open+.01) if v.security_id==b['spin']['child_security_id'] else v for v in ordinary_fixed.bars))
    try:ctx.projection.apply(bad_quote,ctx.projection.descriptor)
    except ValueError:pass
    else:raise ValueError('COMPOUND_ORIGINAL_DISTRIBUTION_WRONG_QUOTE_FALSIFIER')
    state=PortfolioState.from_dict(deepcopy(cp['run']['state']['wealth_core']));ledger=Ledger.from_dict(deepcopy(cp['run']['state']['ledger']))
    cfg=config(cp['base']['policy']);before=deepcopy(state.to_dict());lb=deepcopy(ledger.to_dict())
    need(cfg.transaction_cost_bps==10, 'COMPOUND_ORIGINAL_RESEARCH_SALE_COST_CONVENTION')
    try:apply_supported_entitlements(state,(ctx.projection.original,),bars=(),ledger=ledger,config=cfg)
    except ValueError as error:
        need('SPINOFF_CHILD_OWNERSHIP_REQUIRED' in str(error) and before==state.to_dict() and lb==ledger.to_dict(),
             'COMPOUND_ORIGINAL_UNREVIEWED_CHILD_REFUSAL_AND_ATOMICITY')
    else:raise ValueError('COMPOUND_ORIGINAL_UNREVIEWED_CHILD_GUARD_FALSIFIER')
    wrong_role=deepcopy(cp['run']['state'])
    own,=[v for v in wrong_role['wealth_core']['episodes'].values() if v['security_id']==sid]
    own['current_shares']+=1
    try:actual_role(wrong_role,wrong_role['pending'],b)
    except ValueError:pass
    else:raise ValueError('COMPOUND_ACTUAL_ROLE_FALSIFIER')
    selected_spin=tuple(v for v in fixed.spins if v.source_row_id==b['spin']['source_row_id'])
    audit=apply_supported_entitlements(state,selected_spin,bars=fixed.bars,ledger=ledger,config=cfg)
    spin_proof=spin_postcondition(b,before,state.to_dict(),lb,ledger.to_dict(),audit,cfg.transaction_cost_bps)
    before=deepcopy(state.to_dict());lb=deepcopy(ledger.to_dict())
    result=apply_terminal(state,term,ledger=ledger,session=day,cfg=cfg,phase='OPEN',delivered_raw_open=delivered.raw_open)
    terminal_proof=terminal_postcondition(b,before,state.to_dict(),lb,ledger.to_dict(),result)
    # Packet/source/parser/role guards are also covered by portable removal tests.
    for cursor,pred in ((cp['source_cursor'],'0'*64),(day,cp['run']['checkpoint_sha256'])):
        try:repair.load_repair(Path(out)/OVERLAY,resume_session=cursor,predecessor_checkpoint_sha256=pred)
        except ValueError:pass
        else:raise ValueError('COMPOUND_WRONG_PARENT_OR_CONSUMED_PARSER_FALSIFIER')
    save(Path(out)/QUALIFICATION,dict(passed=True,financial_sessions_advanced=0,source_payload_sha256=sha(encoded(p['source_payload'])),
        binding_sha256=digest(b),original_controller_notional=value,spin=spin_proof,terminal=terminal_proof,
        canonical_primitives_delegated=True,original_financial_source_changed=False,
        actual_native_quote_role_incomplete_child_and_missing_delivery_falsifiers=True,
        original_parent_and_consumed_date_parser_falsifiers=True))
