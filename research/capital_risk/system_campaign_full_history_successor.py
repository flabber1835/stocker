"""Compose complete original parent history with one genuine ordinary append."""
from pathlib import PurePosixPath
import json
from copy import deepcopy
from system_campaign_facts import sha,digest
from full_system_benchmark import need
from system_campaign_bounded_sensor_origin_v2 import strict_json
PARENT='ordinary-successor-origin/parent-checkpoint.json.gz'
NEUTRAL='ordinary-successor-origin/neutral-checkpoint.json.gz'
PROOF='ordinary-successor-origin/neutral-proof.json'

def descriptor_path(entry):
 name=entry['filename'];p=PurePosixPath(name)
 need(type(name) is str and p.name==name and '/' not in name and '\\' not in name
  and name==entry['sha256']+'.json','SUCCESSOR_SAFE_EXACT_HASH_NAMED_INPUT_DESCRIPTOR')
 return 'book/repairs/'+name

def current_commitments(current,spec,input_hash):
 run=current['run']
 need(current['base']==spec['base'] and current['sha256']==digest({k:v for k,v in current.items() if k!='sha256'})
  and run['checkpoint_sha256']==digest({k:v for k,v in run.items() if k!='checkpoint_sha256'})
  and run['state_sha256']==digest(run['state']) and current['source_cursor']==run['state']['last_processed_session']
  and run['input_sha256']==input_hash(current['base'],current['repairs']),
  'SUCCESSOR_ENTIRE_CURRENT_CHECKPOINT_STATE_AND_INPUT_COMMITMENTS')

def verify(root,current,spec,*,member,previous_history,document,input_hash,zero_adoption,earliest,
           parent_path=PARENT,neutral_path=NEUTRAL,proof_path=PROOF):
 """Callbacks read existing bytes or validate DATA; they create no book/state."""
 current_commitments(current,spec,input_hash);count=len(spec['repairs'])
 need(callable(previous_history) and callable(document) and callable(zero_adoption),
  'SUCCESSOR_EXPLICIT_COMPLETE_PREVIOUS_VISITOR_DOCUMENT_AND_ADOPTION_CHECKS')
 if current['sha256']==spec['outer_sha256']:
  need(current['repairs']==spec['repairs'] and current['completed']==spec['measured_closes']
   and current['source_cursor']==spec['selected_session'] and current['run']['input_sha256']==spec['input_sha256'],
   'SUCCESSOR_EXACT_ORIGINAL_PARENT_BEFORE_ANY_NEW_INPUT')
  previous_history(root,current)
  return dict(passed=True,full_inputs=count,new_input_adopted=False,current_sha256=current['sha256'])
 raw=member(parent_path)
 need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'],
  'SUCCESSOR_ACTUAL_ADMITTED_PARENT_ARCHIVE_BYTES_BEFORE_PARSING')
 parent=strict_json(raw)
 need(parent['sha256']==spec['outer_sha256'] and parent['repairs']==spec['repairs']
  and parent['completed']==spec['measured_closes'] and parent['source_cursor']==spec['selected_session']
  and parent['run']['input_sha256']==spec['input_sha256'],'SUCCESSOR_ONLY_GENUINE_ARCHIVED_PARENT')
 previous_history(root,parent)
 need(len(current['repairs'])==count+1 and current['repairs'][:-1]==parent['repairs'],
  'SUCCESSOR_FULL_UNMODIFIED_HISTORY_PLUS_EXACTLY_ONE_DESCRIPTOR')
 entry=current['repairs'][-1];input_raw=member(descriptor_path(entry))
 need(entry['resume_session']==parent['source_cursor'] and entry['predecessor_checkpoint_sha256']==parent['run']['checkpoint_sha256']
  and sha(input_raw)==entry['sha256'] and json.loads(input_raw)==document(parent,member),
  'SUCCESSOR_GENUINE_COMPLETE_NEW_SOURCE_BOUND_INPUT_DOCUMENT')
 neutral_raw=member(neutral_path);neutral=strict_json(neutral_raw)
 event=zero_adoption(neutral,parent,entry['sha256'],earliest)
 need(neutral['repairs']==current['repairs'] and neutral['run']['input_sha256']==current['run']['input_sha256']
  and neutral['run']['state']==parent['run']['state'] and current['completed']>=neutral['completed']
  and current['source_cursor']>=neutral['source_cursor'] and current['base']==neutral['base']==parent['base'],
  'SUCCESSOR_REAL_NEUTRAL_ARCHIVE_AND_ENTIRE_CURRENT_DESCENDANT')
 proof=json.loads(member(proof_path))
 need(proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(neutral_raw),original_outer_sha256=parent['sha256'],
  financial_state_unchanged=True,financial_sessions_advanced=0),'SUCCESSOR_EXACT_ACTUAL_ZERO_SESSION_PROOF')
 # Check all documents, including every original prefix entry, without changing
 # the current checkpoint or feeding a narrowed copy to any previous validator.
 for item in current['repairs']:
  need(sha(member(descriptor_path(item)))==item['sha256'],'SUCCESSOR_EVERY_ORIGINAL_AND_NEW_RAW_INPUT_BYTES')
 return dict(passed=True,full_inputs=count+1,new_input_adopted=True,parent_sha256=parent['sha256'],
  current_sha256=current['sha256'],neutral_sha256=neutral['sha256'],input_successor=deepcopy(event),financial_sessions_advanced=0)
