"""One explicit future-input projection; original archived repairs stay immutable."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from full_system_benchmark import need,save
from system_campaign_facts import digest,sha

CATALOG='research:system-optimization-002/future-input-amendment-catalog/1'
COMPILER='research:system-optimization-002/future-input-amendment-adapter/1'
HYDRATED='research:system-optimization-002/future-input-amendment-private-payload/1'
OUTER='a9b87ca80dbc29e3700173c4c879083266554457aec10e4327c58ee872b860ee'
INNER='dc824901f28255d2ba94aa3c4db83084435e220b811022948c951ec4a403ff9a'
INPUT='ecf65c177e7cea12a5038d0255a4eb3ce1f934d6b3e605370e238dca790c02a9'
CUTOVER='2021-03-31'
SID='1056418588994492299'
TARGET='1e9971280d201cca7ab6eb70bcc66a5849f39e917e0f5ee2365dc363ab821174'
CORRECT='b8aa73d164b41b78948034bc6647c30839d9f38917d9c545bac205b78c301f67'
TARGET_CONTENT='2fee382b500145ee5bfd2c69dcbc0a51e11823732dba7576d1c11baf85963a3f'
CORRECT_CONTENT='ef3b4c2dd20293ecc6cbc1640ff48011e42b3c73ec939a67bf07e23e4516fe5b'
RETIRED_SUPPRESS='52b7295c188c199ae419f96d2de150d1f20f88a27c18d3b74b452e5d40ee0635'
RETIRED_ADD='9e8b247ebedcc4cd74640afef476b81f969bc968ac46524bdb7c59669678e22c'
PRESERVED_ADD='129b55a2378559e00d56b810538be6527998ee19da06d5bd1fecd5005a0ab2e1'
PAYLOAD_NAME='hydrated-future-input-amendment.json'
OVERLAY_NAME='future-input-amendment-overlay.json'
PROJECTION_NAME='derived-following-input-projection.json'


def documents(root,cp):
    result={}
    for descriptor in cp['repairs']:
        h=descriptor['sha256'];need(descriptor['filename']==h+'.json','AMENDMENT_ORIGINAL_FILENAME')
        raw=(root/'book/repairs'/descriptor['filename']).read_bytes()
        need(sha(raw)==h,'AMENDMENT_EVERY_ARCHIVED_INPUT_UNCHANGED')
        result[h]=json.loads(raw)
    return result


def validate_conflict(cp,docs):
    """Data-only exact incident contract, never a checkpoint/state conversion."""
    need((cp['sha256'],cp['run']['checkpoint_sha256'],cp['run']['input_sha256'],cp['source_cursor'])==
         (OUTER,INNER,INPUT,CUTOVER),'AMENDMENT_EXACT_OWN_UNCONSUMED_PREDECESSOR')
    need(TARGET in docs and CORRECT in docs,'AMENDMENT_EXACT_TARGET_AND_PRIOR_CORRECT')
    target,correct=docs[TARGET],docs[CORRECT]
    need(digest(target)==TARGET_CONTENT and digest(correct)==CORRECT_CONTENT,
         'AMENDMENT_ALL_TARGET_AND_CORRECT_FIELDS_EXACT')
    need(target['schema']==correct['schema']=='terminal-repair/1','AMENDMENT_ORDINARY_INPUT_ONLY')
    retired={};preserved={}
    for field,h in (('suppress',RETIRED_SUPPRESS),('add',RETIRED_ADD)):
        rows=[r for r in target[field] if r['security_id']==SID]
        need(len(rows)==1 and digest(rows[0])==h and rows[0]['session']>CUTOVER,
             'AMENDMENT_EXACT_FUTURE_RETIRED_'+field.upper())
        retired[field]=rows[0]
        prior=[r for r in correct[field] if r['security_id']==SID]
        need(len(prior)==1,'AMENDMENT_UNIQUE_PRIOR_APHA_'+field.upper());preserved[field]=prior[0]
    need(retired['suppress']==preserved['suppress']
         and digest(preserved['add'])==PRESERVED_ADD
         and preserved['add']['cash_in_lieu_price_per_delivered_share']==0.
         and preserved['add']['exchange_ratio']==.8381
         and preserved['add']['cash_per_share'] is None,'AMENDMENT_PRESERVE_EXACT_PRIOR_ZERO_FRACTIONAL_PAYMENT')
    changed={k for k in retired['add'] if retired['add'][k]!=preserved['add'][k]}
    need(changed=={'reference','cash_in_lieu_price_per_delivered_share'},'AMENDMENT_ONLY_DECLARED_APHA_TERM_DIFFERENCES')
    additions={};conflicts=set()
    for doc in docs.values():
        if doc['schema']!='terminal-repair/1':continue
        for row in doc['add']:
            key=row['session'],row['security_id'];h=digest(row)
            if key in additions and additions[key]!=h:conflicts.add(key)
            additions[key]=h
    need(conflicts=={('2021-05-03',SID)},'AMENDMENT_ONLY_DECLARED_FUTURE_ORDINARY_CONFLICT')
    return dict(schema='research.future-input-projection-policy/1',cutover_session=CUTOVER,
        predecessor_outer_sha256=OUTER,predecessor_inner_sha256=INNER,predecessor_input_sha256=INPUT,
        base_sha256=digest(cp['base']),target_repair_sha256=TARGET,correct_repair_sha256=CORRECT,
        retired_suppression_sha256=RETIRED_SUPPRESS,retired_addition_sha256=RETIRED_ADD,
        preserved_addition_sha256=PRESERVED_ADD,original_financial_state_edited=False,
        prior_archived_documents_edited=False)


def projection(cp,docs,refs):
    policy=validate_conflict(cp,docs);target=deepcopy(docs[TARGET])
    target['predecessor_checkpoint_sha256']=INNER
    # This is a derived future view, not a replacement for the original input.
    for field in ('suppress','add'):
        target[field]=[r for r in target[field] if r['session']>CUTOVER and r['security_id']!=SID]
    need(len(target['suppress'])==len(target['add'])==4,'AMENDMENT_EXACT_FOUR_NON_APHA_FUTURE_EVENTS')
    need(set(refs)=={CATALOG,COMPILER},'AMENDMENT_NONCIRCULAR_PROJECTION_EVIDENCE')
    target['source_evidence'].extend(dict(reference=r,sha256=h,description='Explicit derived future view; original descriptors remain unchanged.') for r,h in sorted(refs.items()))
    return policy,target


def effective_documents(docs,policy):
    """For explicit common-basis opt-in; the strict conflict fold stays unchanged."""
    need(policy['target_repair_sha256']==TARGET and policy['correct_repair_sha256']==CORRECT
         and policy['retired_suppression_sha256']==RETIRED_SUPPRESS
         and policy['retired_addition_sha256']==RETIRED_ADD
         and policy['preserved_addition_sha256']==PRESERVED_ADD,'AMENDMENT_EXACT_SEMANTIC_VIEW_POLICY')
    result=deepcopy(docs)
    for field,h in (('suppress',RETIRED_SUPPRESS),('add',RETIRED_ADD)):
        before=result[TARGET][field];matches=[r for r in before if digest(r)==h]
        need(len(matches)==1 and matches[0]['session']>policy['cutover_session'],'AMENDMENT_UNIQUE_UNCONSUMED_SEMANTIC_RETIREMENT')
        result[TARGET][field]=[r for r in before if digest(r)!=h]
    return result


class FutureProjection:
    """Canonical ordinary loader/apply remain the sole parsing/arithmetic path."""
    def __init__(self,root,cp,*,payload_name=PAYLOAD_NAME,overlay_name=OVERLAY_NAME):
        self.root=root;self.cp=cp;self.payload_raw=(root/payload_name).read_bytes();self.payload=json.loads(self.payload_raw)
        self.original_docs=documents(root,cp)
        catalog_raw=Path('/driver/system-campaign-future-input-amendment-catalog.json').read_bytes()
        need(self.payload['catalog']==json.loads(catalog_raw)
             and self.payload['projection_evidence']=={CATALOG:sha(catalog_raw),COMPILER:sha(Path(__file__).read_bytes())},
             'AMENDMENT_ACTUAL_PUBLISHED_CATALOG_AND_ADAPTER_BYTES')
        policy,view=projection(cp,self.original_docs,self.payload['projection_evidence'])
        need(self.payload['policy']==policy and self.payload['derived_projection']==view,
             'AMENDMENT_PAYLOAD_EXACT_BOUND_DERIVED_VIEW')
        self.overlay=root/overlay_name;self.overlay_raw=self.overlay.read_bytes();self.activation_sha=sha(self.overlay_raw)
        activation=json.loads(self.overlay_raw)
        expected={**self.payload['projection_evidence'],HYDRATED:sha(self.payload_raw)}
        committed={r['reference']:r['sha256'] for r in activation['source_evidence'] if r['reference'] in expected}
        need(committed==expected and activation['predecessor_checkpoint_sha256']==INNER
             and activation['suppress']==self.payload['new_patch']['suppress']
             and activation['add']==self.payload['new_patch']['add'],'AMENDMENT_ACTIVATION_BINDS_POLICY_PAYLOAD_AND_NEW_FACTS')
        self.projection_path=root/PROJECTION_NAME
        if self.projection_path.exists():need(json.loads(self.projection_path.read_bytes())==view,'AMENDMENT_EXISTING_DERIVED_VIEW_EXACT')
        else:save(self.projection_path,view)
        self.active=False;self.loaded_target=[];self.projected_packets=0

    def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
        obj=self.original_load(path,resume_session=resume_session,predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
        if obj.sha256==self.activation_sha:
            need(resume_session==CUTOVER and predecessor_checkpoint_sha256==INNER
                 and Path(path).read_bytes()==self.overlay_raw,'AMENDMENT_EXACT_CANONICAL_ACTIVATION_BOUNDARY')
            self.active=True
        if obj.sha256==TARGET:self.loaded_target.append(obj)
        return obj

    def apply(self,packet,obj):
        if getattr(obj,'sha256',None)!=TARGET or packet.day<=CUTOVER:
            return self.original_apply(packet,obj)
        need(self.active and any(obj is v for v in self.loaded_target),'AMENDMENT_ONLY_ACTIVATED_CANONICAL_TARGET_OBJECT')
        self.repair._loaded(obj)
        need(obj.model_dump(mode='json',by_alias=True)==self.original_docs[TARGET],
             'AMENDMENT_ORIGINAL_LOADED_TARGET_UNCHANGED')
        self.projected_packets+=1
        return self.original_apply(packet,self.derived)

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest,repair
        self.backtest,self.repair=backtest,repair
        self.original_load,self.original_apply=repair.load_repair,backtest.apply_repair
        self.saved_backtest_load=backtest.load_repair
        self.derived=self.original_load(self.projection_path,resume_session=CUTOVER,predecessor_checkpoint_sha256=INNER)
        repair.load_repair=backtest.load_repair=self.load;backtest.apply_repair=self.apply
        return self

    def __exit__(self,*args):
        self.repair.load_repair=self.original_load;self.backtest.load_repair=self.saved_backtest_load
        self.backtest.apply_repair=self.original_apply
