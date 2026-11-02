"""Registered OWN475 source gate. Legacy source authorities remain unchanged."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from p01_celg_bridge_source import FINANCIAL_CHANGED,verify_rendered_modules,digest,sha

HERE=Path(__file__).parent
SPEC='p01_celg_bridge_predecessor.json'
SCHEMA='research.p01-celg-own475-source-successor/1'
PARENT='518bd498cb44862c921f861d4c7d8e0f18dc0c44f41ea45fd85df22dd936180d'
INNER='b03771e77dd981819ab7fc1ac4484b890445ca06b3753bcbac63199d6ddfd79b'
STATE='9392fd67495b5f17772dc29e27d483fd18faab3b2b6695ec3672fdfe79a339cb'
INPUT='e9c7ebe6c3233cd0035cfc774df6ad2c3bb876ce4a3fe05f24232efad42e4651'
IDENTITY_FIELDS=frozenset(('wealth_core_source_sha256','data_semantics_source_sha256',
                           'research_implementation_sha256'))


def need(value,code):
    if not value:raise ValueError('REFUSED_P01_CELG_BRIDGE_'+code)


def specification():
    spec=json.loads((HERE/SPEC).read_bytes())
    need(spec['root_admission_descriptor_sha256']=='dca11e9849ef106af49262d3b7032f714f74734e0c12c00c474065bf48a0dcbf'
         and spec['outer_sha256']==PARENT and spec['inner_sha256']==INNER
         and spec['state_sha256']==STATE and spec['input_sha256']==INPUT
         and spec['selected_session']=='2019-11-19' and spec['measured_closes']==475
         and spec['financial_predecessor_admitted'] is True and len(spec['repairs'])==9
         and spec['current_tails_zero'] is True and spec['qualification_state_adopted'] is False,
         'EXACT_ROOT_ADMITTED_OWN475_ONLY')
    return spec


def parent_identity(old,spec=None):
    spec=spec or specification()
    need(old['sha256']==PARENT and old['run']['checkpoint_sha256']==INNER
         and old['run']['state_sha256']==STATE and old['run']['input_sha256']==INPUT
         and old['run']['state_sha256']==digest(old['run']['state'])
         and old['run']['checkpoint_sha256']==digest({k:v for k,v in old['run'].items() if k!='checkpoint_sha256'})
         and old['sha256']==digest({k:v for k,v in old.items() if k!='sha256'})
         and old['base']==spec['base'] and old['repairs']==spec['repairs']
         and old['journals']==spec['journals'] and old['completed']==475
         and old['source_cursor']=='2019-11-19','ALL_OWN475_CONTENT_AND_INPUT_BINDINGS')
    return old


def receipt(old,source_map,successor_identity):
    parent_identity(old)
    return dict(schema=SCHEMA,predecessor_outer_sha256=PARENT,predecessor_inner_sha256=INNER,
        predecessor_state_sha256=STATE,predecessor_input_sha256=INPUT,
        predecessor_gzip=specification()['selected_file'],
        predecessor_descriptor_sha256=sha((HERE/SPEC).read_bytes()),
        old_source_restore_proofs=specification()['reused_hosted_old_source_proofs'],
        old_independent_review_sha256=specification()['independent_review_sha256'],
        predecessor_base=old['base'],predecessor_repairs=old['repairs'],
        successor_sources=source_map['successor_financial_sources'],
        source_map_sha256=digest(source_map),successor_identity=successor_identity,
        owner_authorization='OWN475_CELG_TYPED_RIGHT_SOURCE_AND_MARKET_INPUT_BRIDGE_2026_11_02')


def verify_receipt(raw,old,current_base,source_map,identity):
    parent_identity(old)
    need(raw==receipt(old,source_map,identity),'EXACT_REGISTERED_OWN475_RECEIPT')
    previous=old['base']['sources'];sources=current_base['sources']
    need(source_map['predecessor_financial_sources']==previous
         and sources==source_map['successor_financial_sources']
         and {n for n in set(sources)|set(previous) if sources.get(n)!=previous.get(n)}==FINANCIAL_CHANGED,
         'EXACT_FIVE_CANONICAL_SOURCE_PATHS_PLUS_BOUND_PHYSICAL_IDENTITY_MANIFEST')
    need({**current_base,'sources':previous}==old['base'],
         'SOURCE_BOUNDARY_NO_POLICY_INPUT_CAPITAL_OR_COMPARISON_CHANGE')
    before=old['run']['state']['strategy_identity']
    changed={k for k in set(before)|set(identity) if before.get(k)!=identity.get(k)}
    need(changed and changed<=IDENTITY_FIELDS,'ONLY_EXISTING_SOURCE_IDENTITY_HASH_FIELDS')
    return True


def source_adoption(saved,bridge,old,event):
    """Prove canonical startup only added the already committed source watch row."""
    need({k:v for k,v in saved.items() if k not in ('journals','sha256')}
         =={k:v for k,v in bridge.items() if k not in ('journals','sha256')},
         'ZERO_SOURCE_STARTUP_NO_FINANCIAL_OR_REPORTING_MUTATION')
    need(saved['run']['state']=={**old['run']['state'],
         'strategy_identity':bridge['run']['state']['strategy_identity']},
         'ZERO_SOURCE_FULL_STATE_EQUALS_OWN475_EXCEPT_SOURCE_IDENTITY')
    need(saved['chain']==digest(dict(previous=old['chain'],event=event))
         and saved['sha256']==digest({k:v for k,v in saved.items() if k!='sha256'}),
         'EXACT_SOURCE_BOUNDARY_CHAIN_AND_OUTER')
    need(set(saved['journals'])==set(old['journals'])
         and all(saved['journals'][n]==old['journals'][n] for n in old['journals'] if n!='watch')
         and saved['journals']['watch']['bytes']>old['journals']['watch']['bytes'],
         'ONLY_SOURCE_WATCH_COMMITMENT_MAY_GROW')
    return event


class SourceGate:
    def __init__(self,old,source_map,receipt_path,checkpoint_path=None):
        self.old=parent_identity(old);self.source_map=source_map;self.path=Path(receipt_path)
        self.allowed=set();self.adopted=False;self.checkpoint_path=checkpoint_path

    def load(self,path,current_base):
        raw=json.loads(Path(path).read_bytes())
        if raw.get('schema')!=SCHEMA:return self.original_load(path,current_base)
        need(Path(path).resolve()==self.path.resolve(),'ONLY_EXACT_REGISTERED_SOURCE_RECEIPT_PATH')
        _,identity=self.runtime.strategy(current_base['policy'])
        verify_receipt(raw,self.old,current_base,self.source_map,identity)
        binding=dict(receipt=SimpleNamespace(**raw),predecessor=self.old,
                     receipt_sha256=sha(Path(path).read_bytes()))
        self.binding=binding
        base={**current_base,'source_successor_sha256':binding['receipt_sha256']}
        if self.adopted:
            from research.pooled_vacancy_funding.journal import read_checkpoint
            need(self.checkpoint_path is not None,'SOURCE_EPOCH_CONTINUATION_CHECKPOINT_REQUIRED')
            saved=read_checkpoint(self.checkpoint_path)
            need(saved['sha256'] in self.allowed and saved['base']==base,
                 'ONLY_VERIFIED_ZERO_SESSION_SOURCE_EPOCH_CONTINUATION')
            return base,None  # Already committed source event must not be appended a second time.
        return base,binding

    def validate(self,saved,binding,base):
        if getattr(binding['receipt'],'schema',None)!=SCHEMA:
            return self.original_validate(saved,binding,base)
        if saved['source_cursor']==self.old['source_cursor'] and saved['sha256'] in self.allowed:
            need(saved['base']==base,'REGISTERED_ZERO_SESSION_ADOPTION_BASE');return
        return self.original_validate(saved,binding,base)

    def _allow(self,saved):
        need(saved['source_cursor']==self.old['source_cursor'] and saved['completed']==475,
             'ONLY_VERIFIED_ZERO_SESSION_BOUNDARY_CAN_BE_REGISTERED')
        self.allowed.add(saved['sha256'])

    def allow_source(self,saved,bridge):
        source_adoption(saved,bridge,self.old,self.module.boundary_event(self.binding))
        self._allow(saved);self.adopted=True

    def allow_input(self,saved,source,overlay_sha256):
        from system_campaign_pxd_pause import adoption
        adoption(saved,source,overlay_sha256,'2019-11-20')
        self._allow(saved)

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import source_successor,runtime
        self.module,self.runtime=source_successor,runtime
        self.original_load,self.original_validate=source_successor.load_successor,source_successor.validate_boundary
        source_successor.load_successor=self.load;source_successor.validate_boundary=self.validate
        return self

    def __exit__(self,*args):
        self.module.load_successor=self.original_load;self.module.validate_boundary=self.original_validate
