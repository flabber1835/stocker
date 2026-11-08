"""The genuine admitted full19 history and one canonical bounded append."""
import gzip,json
from pathlib import Path
import system_campaign_p03_STML_source as source
import system_campaign_full_history_successor as original
import system_campaign_bounded_sensor_runtime_v2 as previous
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
from system_campaign_facts import sha,digest
from full_system_benchmark import need

PREFIX='bounded-successors/'+source.ROOT
PARENT=PREFIX+'/origin/parent-checkpoint.json.gz'
DIRECTORY=PREFIX+'/adoption'
NEUTRAL=DIRECTORY+'/checkpoint.json.gz'
PROOF=DIRECTORY+'/proof.json'
OVERLAY=PREFIX+'/input-overlay.json'
SOURCE=PREFIX+'/event-source.json'
CATALOG=PREFIX+'/source-catalog.json'
QUALIFICATION=PREFIX+'/packet-qualification.json'

def spec():
 from system_campaign_financial_partial import root_spec
 return root_spec('P03',source.ROOT)

def full_parent(root,parent):
 target=spec();source.parent_contract(parent,target)
 result=previous.full_models(root,parent)
 previous.origins.load(root,parent,previous.catalog(),previous.typed(root),previous.metadata())
 return result

def archived_parent(member):
 target=spec();raw=member(PARENT)
 need(dict(bytes=len(raw),sha256=sha(raw))==target['selected_file'],'STML_HISTORY_UNSUBSTITUTED_GENUINE_SELECTED_PARENT_GZIP')
 parent=strict_json(raw);source.parent_contract(parent,target);return parent

def document(parent,member):
 value=source.catalog();doc=source.document(parent,value=value)
 need(member(CATALOG)==source.encoded(value) and member(SOURCE)==source.encoded(value['market_source'])
  and member(OVERLAY)==source.encoded(doc),'STML_HISTORY_COMPLETE_NEW_SOURCE_CATALOG_MARKET_AND_TYPED_INPUT')
 q=json.loads(member(QUALIFICATION))
 need(q['passed'] is True and q['catalog_sha256']==sha(source.encoded(value))
  and q['typed_document_sha256']==sha(source.encoded(doc)) and q['market_source_sha256']==value['market_source_sha256']
  and q['financial_sessions_advanced']==0 and type(q['financial_sessions_advanced'])is int
  and q['packet']['actual_packet_checks']==1 and q['packet']['wrong_predecessor_and_consumed_cursor_refused'] is True
  and q['packet']['original_incomplete_guard_retained'] is q['packet']['no_cash_or_right_price_created'] is True,
  'STML_HISTORY_ENTIRE_ORIGINAL_HOSTED_PACKET_AND_PARSER_QUALIFICATION')
 return doc

def history(root,current,*,member,previous_history=full_parent):
 return original.verify(root,current,spec(),member=member,previous_history=previous_history,document=document,
  input_hash=lambda base,repairs:digest(dict(base=base,repairs=repairs)),zero_adoption=adoption,
  earliest=source.DAY,parent_path=PARENT,neutral_path=NEUTRAL,proof_path=PROOF)

def full(root,current):
 root=Path(root);return history(root,current,member=lambda n:(root/n).read_bytes())

def boundary(parent,neutral,member,rows):
 target=spec();source.parent_contract(parent,target)
 need(archived_parent(member)==parent,'STML_HISTORY_REAL19_ARCHIVE_BEFORE_NEUTRAL20_REVIEW')
 doc=document(parent,member);raw=source.encoded(doc);event=adoption(neutral,parent,sha(raw),source.DAY)
 neutral_raw=member(NEUTRAL);proof=json.loads(member(PROOF))
 need(strict_json(neutral_raw)==neutral and len(neutral['repairs'])==20 and neutral['repairs'][:-1]==parent['repairs']
  and neutral['run']['state']==parent['run']['state'] and proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(neutral_raw),
   original_outer_sha256=parent['sha256'],financial_state_unchanged=True,financial_sessions_advanced=0),
  'STML_HISTORY_ACTUAL_CANONICAL_NEUTRAL20_ENTIRE19_HISTORY_AND_UNCHANGED_STATE')
 need(gzip.decompress(member(DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
  'STML_HISTORY_ALL_RETAINED_CORRELATION_ROWS_NO_NEW_OBSERVATION')
 watch=member('book/watch.jsonl');before,after=parent['journals']['watch'],neutral['journals']['watch']
 need(sha(watch[:before['bytes']])==before['prefix_sha256'] and sha(watch[:after['bytes']])==after['prefix_sha256']
  and [json.loads(v) for v in watch[before['bytes']:after['bytes']].splitlines()]==[event],
  'STML_HISTORY_ONLY_ONE_CANONICAL_SUCCESSOR_WATCH_APPEND')
 return dict(passed=True,parent_outer_sha256=parent['sha256'],neutral_outer_sha256=neutral['sha256'],
  neutral_gzip_sha256=sha(neutral_raw),parent_inputs=19,current_inputs=20,financial_sessions_advanced=0,event=event)
