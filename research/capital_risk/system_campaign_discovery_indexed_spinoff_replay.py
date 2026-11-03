"""Indexed-proof epochs and persistent unvalued claims around frozen replay."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

from full_system_benchmark import need,save
from system_campaign_discovery_context import TAINT,digest,encoded
from system_campaign_discovery_spinoff_deferral import UnresolvedClaim
from system_campaign_discovery_indexed_spinoff_parent import exact,validate_contents,indexed_seeds
import system_campaign_discovery_suffix_replay as original

def claim_key(claim):return claim['session'],claim['parent_security_id'],claim['source_row_id']

def add_claims(registry,event,*,source_sha256,input_sha256):
 if event['kind']!='SPINOFF_UNRESOLVED_ENTITLEMENT_DEFERRED':return
 need(event['authority']==TAINT and event['source_sha256']==source_sha256 and event['input_sha256']==input_sha256,
  'INDEXED_SPIN_CLAIM_EVENT_SAME_SOURCE_INPUT_AND_AUTHORITY')
 proof=event['context']['entitlement_proof']
 need(proof['authority']==TAINT and proof['session']==event['session'] and proof['input_sha256']==input_sha256
  and proof['prior_state_sha256']==event['prior_state_sha256'] and proof['financial_authority'] is False
  and proof['all_supplied_held_legs_deferred'] is True and proof['partial_application'] is False,
  'INDEXED_SPIN_CLAIM_ONLY_COMPLETE_UNSETTLED_HELD_SET')
 for leg in proof['affected_held_legs']:
  raw=leg['unresolved_claim']
  if raw is None:continue
  claim=UnresolvedClaim.model_validate(raw).model_dump()
  need(encoded(raw)==encoded(claim) and claim['financial_authority'] is False
   and claim['entitlement_status']=='UNRESOLVED_UNVALUED_NOT_SETTLED' and claim['session']==event['session']
   and claim['parent_episode_facts'] and 'HELD' in claim['roles'],
   'INDEXED_SPIN_EXPLICIT_FULL_UNVALUED_CLAIM_NO_DEFAULTS_OR_QUANTITY_INVENTION')
  term=leg['source_term']
  need(all(claim[k]==term[k] for k in ('session','parent_ticker','parent_security_id','child_ticker','child_security_id','source_row_id'))
   and claim['parent_episode_facts']==leg['parent_episode_facts'] and claim['roles']==leg['roles']
   and leg['disposition']=='UNRESOLVED_UNVALUED_NOT_SETTLED'
   and any(v['source_row_id']==claim['source_row_id'] for v in proof['native_source_legs']),
   'INDEXED_SPIN_CLAIM_EXACT_SUPPLIED_RAW_LEG_EPISODE_AND_NATIVE_IDENTITY')
  key=claim_key(claim)
  need(key not in registry or registry[key]==claim,'INDEXED_SPIN_NO_AMBIGUOUS_DUPLICATE_CLAIM')
  registry[key]=deepcopy(claim)

def reconstruct_claims(events,*,source_sha256,input_sha256):
 claims={}
 for event in events:add_claims(claims,event,source_sha256=source_sha256,input_sha256=input_sha256)
 return claims

def claim_rows(registry):return [registry[key] for key in sorted(registry)]
def claim_commitment(registry,events):
 return dict(rows=len(registry),sha256=digest(claim_rows(registry)),event_commitment=deepcopy(events))

class ContinuedContext(original.ContinuedContext):
 def __init__(self,output,*,source_sha256,previous,saved,bindings=None):
  super().__init__(output,source_sha256=source_sha256,previous=previous,saved=saved,bindings=bindings)
  self.claim_input_sha256=saved['runtime_checkpoint']['input_sha256']
  events=original.verify_chain((Path(previous)/'discovery-events.jsonl').read_bytes(),saved['events'])
  self.unvalued_claims=reconstruct_claims(events,source_sha256=source_sha256,input_sha256=self.claim_input_sha256)
  expected=claim_commitment(self.unvalued_claims,saved['events'])
  need(saved.get('unvalued_spinoff_claims',expected)==expected
   and ('unvalued_spinoff_claims' in saved or not self.unvalued_claims),
   'INDEXED_SPIN_EXACT_COMMITTED_CLAIM_REGISTRY_RECONSTRUCTED_NEVER_RESTARTED')
  save(Path(output)/'unvalued-claim-seed-admission.json',dict(authority=TAINT,source_sha256=source_sha256,
   input_sha256=self.claim_input_sha256,commitment=expected,claims=claim_rows(self.unvalued_claims),
   parent_exit_or_absence_never_erases_claim=True,financial_authority=False,production_contacted=False))

 def emit(self,kind,sid=None,*,bypass=False,**context):
  result=super().emit(kind,sid,bypass=bypass,**context)
  if kind=='SPINOFF_UNRESOLVED_ENTITLEMENT_DEFERRED':
   event=dict(kind=kind,authority=TAINT,source_sha256=self.source_sha256,input_sha256=self.current[0].input_sha256,
    session=self.current[1].session,prior_state_sha256=self.current[0].state.state_hash,context=context)
   add_claims(self.unvalued_claims,event,source_sha256=self.source_sha256,input_sha256=self.claim_input_sha256)
  return result

 def claim_commitment(self):return claim_commitment(self.unvalued_claims,self.commitment())

def seed_book(book,previous,saved,spec):
 """Retain each immutable prior epoch once; recover only the working journals."""
 book=Path(book);previous=Path(previous);book.mkdir()
 lineage=book.parent/'lineage/diagnostic-predecessor';lineage.mkdir(parents=True)
 covered=set();copied={}
 for name,entry in spec['full_inventory'].items():
  if name.startswith('lineage/'):continue
  src=previous/name;target=lineage/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
  need(target.stat().st_size==entry['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest()==entry['sha256'],
   'INDEXED_SPIN_EXACT_IMMEDIATE_PARENT_NONLINEAGE_COPY')
 for epoch in spec['retained_lineage_epochs']:
  need(digest(epoch['inventory'])==epoch['epoch_sha256'],'INDEXED_SPIN_FLAT_RETAINED_EPOCH_COMMITMENT')
  prefix=epoch['source_prefix'];destination=book.parent/'lineage/epochs'/epoch['epoch_sha256']
  need(not destination.exists(),'INDEXED_SPIN_NO_DUPLICATE_OR_RECURSIVE_EPOCH_COPY')
  for relative,entry in epoch['inventory'].items():
   name=prefix+relative;need(spec['full_inventory'].get(name)==entry and name not in covered,'INDEXED_SPIN_EXACT_RETAINED_EPOCH_MEMBERSHIP')
   target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(previous/name,target)
   need(target.stat().st_size==entry['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest()==entry['sha256'],
    'INDEXED_SPIN_ALL_HISTORICAL_CP_PROOF_JOURNAL_AND_TAIL_BYTES_RETAINED')
   covered.add(name)
  copied[epoch['epoch_sha256']]=dict(source_prefix=prefix,inventory=epoch['inventory'])
 need(covered=={n for n in spec['full_inventory'] if n.startswith('lineage/')},'INDEXED_SPIN_NO_OLD_LINEAGE_FILE_DROPPED')
 save(book.parent/'lineage/retained-epochs.json',dict(authority=TAINT,epochs=copied,
  immediate_parent_checkpoint_sha256=spec['diagnostic_checkpoint_sha256'],recursive_cumulative_archive=False,
  financial_authority=False,production_contacted=False))
 for name,entry in saved['journals'].items():
  raw=(previous/'diagnostic-book'/(name+'.jsonl')).read_bytes();original.verify_prefix(raw,entry,last=True)
  original.write_new(book/(name+'.jsonl'),raw)
 (book/'retained-checkpoints').mkdir()

def suffix_tree(raw):
 tree=original.suffix_tree(raw)
 cp,=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='checkpoint']
 changes=[n for n in ast.walk(cp) if isinstance(n,ast.Call) and ast.unparse(n.func)=='value.update'
  and any(k.arg=='retained_anchor_qualifications' for k in n.keywords)]
 need(len(changes)==1,'INDEXED_SPIN_ONE_CLAIM_REGISTRY_CHECKPOINT_COMMITMENT_SITE')
 changes[0].keywords.append(ast.keyword(arg='unvalued_spinoff_claims',value=ast.parse('context.claim_commitment()',mode='eval').body))
 return ast.fix_missing_locations(tree)

def replay(root,parent,output,*,selected_file,strict_admission_sha256,previous,spec,anchors,context_class=None,anchor_gate=None):
 saved=validate_contents(previous,spec);seeds,evidence=indexed_seeds(previous,saved,spec)
 save(Path(output)/'indexed-anchor-seed-admission.json',dict(schema='research.indexed-diagnostic-anchor-seed-admission/1',
  authority=TAINT,parent_checkpoint_sha256=spec['diagnostic_checkpoint_sha256'],old_commitment=saved['retained_anchor_qualifications'],
  old_index_and_tail_evidence={k:v for k,v in evidence.items() if k!='committed_proofs'},
  source_sha256=spec['source_sha256'],input_sha256=spec['input_sha256'],seed_proofs=seeds,seed_proofs_sha256=digest(seeds),
  only_committed_qualified_uses_seeded=True,old_files_preserved=True,financial_authority=False,production_contacted=False))
 def selected_seeds(old,cp,source):
  need(Path(old)==Path(previous) and cp==saved and source==spec['source_sha256'],'INDEXED_SPIN_EXACT_SEED_CALL_BINDING')
  return deepcopy(seeds)
 def selected_book(book,old,cp):
  need(Path(old)==Path(previous) and cp==saved,'INDEXED_SPIN_EXACT_WORKING_BOOK_PARENT')
  return seed_book(book,old,cp,spec)
 fn,=[deepcopy(n) for n in ast.parse(exact(original)).body if isinstance(n,ast.FunctionDef) and n.name=='replay']
 scope=dict(vars(original),validate_contents=validate_contents,qualified_anchor_seeds=selected_seeds,
  seed_book=selected_book,ContinuedContext=ContinuedContext,suffix_tree=suffix_tree)
 exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<exact-frozen-suffix-new-indexed-epoch-namespace>','exec'),scope)
 return scope['replay'](root,parent,output,selected_file=selected_file,strict_admission_sha256=strict_admission_sha256,
  previous=previous,spec=spec,anchors=anchors,context_class=context_class,anchor_gate=anchor_gate)
