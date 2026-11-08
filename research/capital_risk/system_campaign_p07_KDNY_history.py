"""Complete genuine full26 history and one exact canonical KDNY append."""
import gzip,json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
import system_campaign_full_history_successor as original
import system_campaign_postclose_distribution_models as previous
import system_campaign_p07_KDNY_source as source

PREFIX='bounded-successors/'+source.ROOT
PARENT=PREFIX+'/origin/parent-checkpoint.json.gz'
DIRECTORY=PREFIX+'/adoption'
NEUTRAL=DIRECTORY+'/checkpoint.json.gz'
PROOF=DIRECTORY+'/proof.json'
OVERLAY=PREFIX+'/input-overlay.json'
SOURCE=PREFIX+'/event-source.json'
CATALOG=PREFIX+'/source-catalog.json'
QUALIFICATION=PREFIX+'/packet-qualification.json'
PRIVATE=PREFIX+'/original-chinook-witnesses/'+source.original.PRIVATE


def spec():
 from system_campaign_financial_partial import root_spec
 return root_spec('P07',source.ROOT)


def full_parent(root,parent):
 source.parent_contract(parent,spec());result=previous.full(root,parent)
 need(result['full_inputs']==26,'KDNY_HISTORY_WHOLE_ORIGINAL_GENUINE26_VISITOR')
 return result


def archived_parent(member):
 target=spec();raw=member(PARENT)
 need(dict(bytes=len(raw),sha256=sha(raw))==target['selected_file'],'KDNY_HISTORY_UNSUBSTITUTED_GENUINE1403_GZIP')
 parent=strict_json(raw);source.parent_contract(parent,target);return parent


def document(parent,member):
 value=source.catalog();doc=source.document(parent,value=value)
 need(member(CATALOG)==source.encoded(value) and member(SOURCE)==source.encoded(value['market_source'])
  and member(PRIVATE)==source.encoded(value['original_chinook_private_event']) and member(OVERLAY)==source.encoded(doc),
  'KDNY_HISTORY_COMPLETE_CATALOG_MARKET_ORIGINAL_PRIVATE_EVENT_AND_TYPED_INPUT')
 q=json.loads(member(QUALIFICATION));packet=q['packet']
 need(q['schema']=='research.P07-KDNY-zero-financial-packet-preparation/1' and q['passed'] is True
  and q['catalog_sha256']==sha(source.encoded(value)) and q['typed_document_sha256']==sha(source.encoded(doc))
  and q['market_source_sha256']==value['market_source_sha256']
  and q['original_private_event_sha256']==value['original_chinook_private_event_sha256']
  and q['financial_sessions_advanced']==0 and type(q['financial_sessions_advanced'])is int
  and q['retained_inputs']==[dict(descriptor=d,loaded_sha256=d['sha256']) for d in parent['repairs']]
  and packet['actual_packet_checks']==2 and packet['actual_selected_signal_range']==[40.,44.]
  and all(packet[k]is True for k in ('unselected_has_no_right_value','native_day_bar_preserved',
   'effective_day_quote_absent','original_incomplete_guard_retained','wrong_predecessor_and_consumed_native_cursor_refused','no_financial_transition')),
  'KDNY_HISTORY_COMPLETE_ORIGINAL_HOSTED_PACKET_AND_ALL26_PARSER_QUALIFICATION')
 return doc


def history(root,current,*,member,previous_history=full_parent):
 return original.verify(root,current,spec(),member=member,previous_history=previous_history,document=document,
  input_hash=lambda b,r:digest(dict(base=b,repairs=r)),zero_adoption=adoption,earliest=source.NATIVE,
  parent_path=PARENT,neutral_path=NEUTRAL,proof_path=PROOF)


def full(root,current):
 root=Path(root);return history(root,current,member=lambda n:(root/n).read_bytes())


def boundary(parent,neutral,member,rows):
 target=spec();source.parent_contract(parent,target)
 need(archived_parent(member)==parent,'KDNY_HISTORY_REAL26_ARCHIVE_BEFORE_NEUTRAL27_REVIEW')
 doc=document(parent,member);event=adoption(neutral,parent,sha(source.encoded(doc)),source.NATIVE)
 raw=member(NEUTRAL);proof=json.loads(member(PROOF))
 need(strict_json(raw)==neutral and len(neutral['repairs'])==27 and neutral['repairs'][:-1]==parent['repairs']
  and neutral['run']['state']==parent['run']['state'] and proof==dict(event=event,actual_checkpoint_gzip_sha256=sha(raw),
   original_outer_sha256=parent['sha256'],financial_state_unchanged=True,financial_sessions_advanced=0),
  'KDNY_HISTORY_ACTUAL_CANONICAL_NEUTRAL27_ENTIRE26_AND_UNCHANGED_STATE')
 need(gzip.decompress(member(DIRECTORY+'-correlation-inputs.jsonl.gz'))==b''.join(rows),
  'KDNY_HISTORY_ALL_ORIGINAL_RETAINED_CORRELATION_ROWS_NO_NEW_OBSERVATION')
 watch=member('book/watch.jsonl');before,after=parent['journals']['watch'],neutral['journals']['watch']
 need(sha(watch[:before['bytes']])==before['prefix_sha256'] and sha(watch[:after['bytes']])==after['prefix_sha256']
  and [json.loads(v) for v in watch[before['bytes']:after['bytes']].splitlines()]==[event],
  'KDNY_HISTORY_ONLY_ONE_CANONICAL_SUCCESSOR_WATCH_APPEND')
 return dict(passed=True,parent_outer_sha256=parent['sha256'],neutral_outer_sha256=neutral['sha256'],
  neutral_gzip_sha256=sha(raw),parent_inputs=26,current_inputs=27,financial_sessions_advanced=0,event=event)
