"""Complete genuine P07 history plus one original canonical input adoption."""
from pathlib import Path
import json
import system_campaign_full_history_successor as original
import system_campaign_p07_saved_proofs as saved
from system_campaign_facts import sha,digest
from system_campaign_pxd_pause import adoption
from system_campaign_bounded_sensor_origin_v2 import strict_json
from full_system_benchmark import need

def paths(spec):
 saved.metadata(spec);prefix='distribution-successors/'+spec['root_admission_sha256']
 return dict(PARENT=prefix+'/origin/parent-checkpoint.json.gz',NEUTRAL=prefix+'/adoption/checkpoint.json.gz',
  PROOF=prefix+'/adoption/proof.json',DIRECTORY=prefix+'/adoption',OVERLAY=prefix+'/input-overlay.json',
  PAYLOAD=prefix+'/source-payload.json',QUALIFICATION=prefix+'/packet-qualification.json',
  RETAINED_QUALIFICATION=prefix+'/retained-input-stack.json',OBSERVATION=prefix+'/observation')

def archived_parent(spec,member):
 raw=member(paths(spec)['PARENT'])
 need(dict(bytes=len(raw),sha256=sha(raw))==spec['selected_file'],'POSTCLOSE_HISTORY_GENUINE_SELECTED_PARENT_GZIP_BEFORE_PARSE')
 parent=strict_json(raw);saved.parent_contract(parent,spec);return parent

def history(root,current,spec,*,member,document,previous_history=None):
 names=paths(spec)
 previous=(lambda where,parent:saved.full_parent(where,parent,spec)) if previous_history is None else previous_history
 return original.verify(root,current,spec,member=member,previous_history=previous,document=document,
  input_hash=lambda base,repairs:digest(dict(base=base,repairs=repairs)),zero_adoption=adoption,earliest='2023-07-05',
  parent_path=names['PARENT'],neutral_path=names['NEUTRAL'],proof_path=names['PROOF'])

def boundary(parent,neutral,spec,member,rows,*,document,packet_qualification):
 names=paths(spec);saved.parent_contract(parent,spec)
 need(archived_parent(spec,member)==parent,'POSTCLOSE_HISTORY_UNSUBSTITUTED_ACTUAL_PARENT25')
 doc=document(parent,member);raw=member(names['OVERLAY'])
 need(json.loads(raw)==doc and callable(packet_qualification),'POSTCLOSE_HISTORY_COMPLETE_INPUT_RECONSTRUCTION_AND_PACKET_REVIEW')
 event=adoption(neutral,parent,sha(raw),'2023-07-05');neutral_raw=member(names['NEUTRAL'])
 need(strict_json(neutral_raw)==neutral and len(neutral['repairs'])==26 and neutral['repairs'][:-1]==parent['repairs']
  and neutral['run']['state']==parent['run']['state'],'POSTCLOSE_HISTORY_GENUINE_NEUTRAL26_ALL_25_INPUTS_AND_STATE_RETAINED')
 proof=json.loads(member(names['PROOF']))
 need(proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(neutral_raw),original_outer_sha256=parent['sha256'],
  financial_state_unchanged=True,financial_sessions_advanced=0),'POSTCLOSE_HISTORY_EXACT_ACTUAL_ZERO_DAY_ADOPTION_PROOF')
 import gzip
 need(gzip.decompress(member(names['DIRECTORY']+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
  'POSTCLOSE_HISTORY_UNCHANGED_ALL_ORIGINAL_CORRELATION_ROWS')
 watch=member('book/watch.jsonl');a,b=parent['journals']['watch'],neutral['journals']['watch']
 need(sha(watch[:a['bytes']])==a['prefix_sha256'] and sha(watch[:b['bytes']])==b['prefix_sha256']
  and [json.loads(v) for v in watch[a['bytes']:b['bytes']].splitlines()]==[event],'POSTCLOSE_HISTORY_ONE_CANONICAL_INPUT_WATCH_APPEND_ONLY')
 packet_qualification(parent,spec,member)
 return dict(passed=True,parent_sha256=parent['sha256'],neutral_sha256=neutral['sha256'],neutral_gzip_sha256=sha(neutral_raw),
  original_inputs=25,current_inputs=26,event=event,financial_sessions_advanced=0)
