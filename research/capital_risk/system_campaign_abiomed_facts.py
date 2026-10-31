"""Hosted ABMD source hydration and a separately bound third sensor input."""
from dataclasses import asdict
import csv,io,json,zipfile
from pathlib import Path
from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha
from system_campaign_abiomed_input import SID,NATIVE,DAY,SCHEMA

HERE=Path(__file__).resolve().parent
CONTRACT='system-campaign-abiomed-sensor-contract.json'
PRIVATE='hydrated-abiomed-sensor-event.json'
EVIDENCE=(('contract',CONTRACT),('typed-codec','system_campaign_abiomed_input.py'),
 ('sensor-adapter','system_campaign_abiomed_sensor.py'),('prefix-reviewer','system_campaign_abiomed_review.py'),
 ('semantic-composition','system_campaign_abiomed_basis.py'),('factual-hydration','system_campaign_abiomed_facts.py'),
 ('canonical-qualification','system_campaign_abiomed_gate.py'))


def evidence(root):
    values=[dict(reference='research:system-optimization-002/abiomed-sensor/'+label+'/1',
                 sha256=sha((HERE/name).read_bytes()),description='Exact ZGNX sensor input contract, adapter or qualification implementation.')
            for label,name in EVIDENCE]
    values.append(dict(reference='research:system-optimization-002/abiomed-sensor/private-event/1',
                       sha256=sha((root/PRIVATE).read_bytes()),description='Full frozen native, source witnesses and event quote absence; not a right valuation.'))
    return values


def hydrate(old,out):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    c=json.loads((HERE/CONTRACT).read_bytes());dates=axis()
    need(c['security_id']==SID and c['native_session']==NATIVE and c['session']==DAY
         and c['cash_consideration_range']==[380.,415.] and c['mandatory_remaining_common_share_entitlement']
         and c['preopen_completion_confirmed'] and not c['tender_participation_assumed']
         and not c['later_payment_information_used'] and not c['production_contacted']
         and dates[dates.index(NATIVE)+1]==DAY,'ABIOMED_EXACT_PRIMARY_CONTRACT_AND_CALENDAR')
    actions=inputs.load_actions(Path('/frozen/bundle'))
    native,=[v for v in actions.terminal.get(NATIVE,()) if v.security_id==SID]
    need(asdict(native)==c['native'] and digest(asdict(native))==c['native_term_sha256']
         and not native.completeness(0)[0],'ABIOMED_ACTUAL_INCOMPLETE_NATIVE')
    need(not any(v.security_id==SID for v in actions.terminal.get(DAY,())), 'ABIOMED_NO_NATIVE_EFFECTIVE_COLLISION')
    wanted={(w['session'],w['security_id']):w for w in c['source_witnesses']};found={};event=[]
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for row in inputs._archive_rows(archive,'observations-2022.csv.gz'):
            key=row['session'],row['security_id']
            if key in wanted:
                w=wanted[key];need(key not in found and digest(row)==w['source_observation_sha256']
                    and all(row[k]==v for k,v in w.items() if k!='source_observation_sha256'),'ABIOMED_EXACT_FULL_SOURCE_WITNESS')
                found[key]=row
            if key==(DAY,SID):event.append(row)
    need(set(found)==set(wanted) and not event and c['event_source_quote_present'] is False,
         'ABIOMED_FULL_WITNESSES_AND_EXACT_EVENT_QUOTE_ABSENCE')
    raw=(old/'provider-source/SHARADAR_ACTIONS.zip').read_bytes();need(sha(raw)==c['provider_archive_sha256'],'ABIOMED_FROZEN_PROVIDER_ARCHIVE')
    rows=[]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in z.namelist():
            with z.open(name) as f:
                for r in csv.DictReader(io.TextIOWrapper(f,encoding='utf8',newline='')):
                    if r['date']==NATIVE and 'ABMD' in (r['ticker'],r['contraticker']):rows.append(r)
    need(digest(rows)==c['provider_rows_sha256'] and [digest(r) for r in rows]==c['provider_row_sha256'],
         'ABIOMED_ALL_ORIGINAL_PROVIDER_ROWS')
    save(out/PRIVATE,dict(schema='research.abiomed-sensor-private-event/1',contract=c,actual_native=asdict(native),
        source_witnesses=[found[k] for k in sorted(found)],provider_rows=rows,session=DAY,security_id=SID,
        source_quote_present=False,split_ratio='1',source_metadata_unchanged=True,right_market_price_observed=False))
    return native


def overlay(cp,out):
    need(cp['source_cursor']<NATIVE and cp['completed']>0
         and cp['run']['input_sha256']==digest(dict(base=cp['base'],repairs=cp['repairs'])),
         'ABIOMED_UNCONSUMED_FULL_OWN_INPUT_COMMITMENT')
    c=json.loads((HERE/CONTRACT).read_bytes())
    doc=dict(schema=SCHEMA,predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],native_session=NATIVE,
        session=DAY,security_id=SID,native_term_sha256=c['native_term_sha256'],sensor_only=True,
        require_unowned_and_unordered=True,consideration_range='380<=cash_plus_nontransferable_right<=415',
        treatment='RECALENDAR_INCOMPLETE_TERM_AND_CERTIFY_ALL_COMPARISONS',source_evidence=evidence(out))
    path=out/'abiomed-sensor-input.json';save(path,doc);return path


def retained_completion(root, cp, out=None):
    """Validate the actual adopted scope; retain its ORIGINAL inner binding."""
    from system_campaign_completion_basis import validate
    from system_campaign_completion_facts import (CONTRACT as OLD_CONTRACT, CATALOG,
        PRIVATE as OLD_PRIVATE, OVERLAY as OLD_OVERLAY, expected_repair,
        evidence as old_evidence)
    from system_campaign_completion_scope import InputCodec
    models = validate(root, cp)
    need(len(models) == 1, 'ABIOMED_EXACT_RETAINED_GUARDED_COMPLETION_INPUT')
    descriptor, = [value for value in cp['repairs'] if value['sha256'] == models[0].sha256]
    target = root
    if out is not None:
        catalog = json.loads((HERE / CATALOG).read_bytes())
        group = catalog['commitment_group']
        for name in (OLD_PRIVATE, OLD_OVERLAY, group['private_file'], group['overlay_file']):
            raw = (root / name).read_bytes()
            path = out / name
            if path.exists():
                need(path.read_bytes() == raw, 'ABIOMED_RETAINED_COMPLETION_EXISTING_EXACT_BYTES')
            else:
                path.write_bytes(raw)
        target = out
    # The old input was admitted at September30. Never bind that old repair to
    # the current November checkpoint merely because it is now the predecessor.
    body = expected_repair(target, descriptor['predecessor_checkpoint_sha256'])
    need(body == models[0].canonical_repair
         and [row.model_dump() for row in models[0].source_evidence] == old_evidence(target),
         'ABIOMED_EXACT_OLD_SCOPE_BODY_BINDING_AND_EIGHT_EVIDENCE_REFS')
    return InputCodec(body, old_evidence(target))
