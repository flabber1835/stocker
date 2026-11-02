"""Exact intraday source facts for a separately typed unowned closing scope."""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import csv
import io
import json
from pathlib import Path
import zipfile

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
from system_campaign_close_scope import SCHEMA, SCOPE, NATIVES, COMPLETIONS, parse, require_absent, require_intents
from system_campaign_2021_completions_facts import require_witness, require_alias_archive
from system_campaign_six_model_preflight import SixModelPreflight
from system_campaign_action_preflight import require_disjoint

HERE = Path(__file__).resolve().parent
CONTRACT = 'system-campaign-twnk-close-contract.json'
PRIVATE = 'hydrated-twnk-close-fact.json'
OVERLAY = 'twnk-guarded-close-input.json'
IMPLEMENTATIONS = ('system_campaign_close_scope.py', 'system_campaign_close_facts.py',
                  'system_campaign_close_basis.py', 'system_campaign_close_gate.py',
                  'system_campaign_close_review.py')
STEM = 'research:system-optimization-002/twnk-close/'


def contract():
    value = json.loads((HERE / CONTRACT).read_bytes());event = value['event'];term = event['added']
    need(value['schema'] == 'research.guarded-close-conversion-contract/1' and value['scope'] == SCOPE
         and len(value['inherited_sources']) == 247
         and not any(value[k] for k in ('canonical_financial_source_changed', 'provider_metadata_upgraded',
                                       'new_owned_settlement_model', 'production_contacted')),
         'CLOSE_FACTS_EXACT_TYPED_CONTRACT_NO_FINANCIAL_RULE_CHANGE')
    need({event['security_id']: event['native_session']} == NATIVES
         and {event['security_id']: event['session']} == COMPLETIONS
         and event['last_trading_session'] == event['native_session']
         and event['mandatory_remaining_common_share_entitlement'] is True
         and event['preopen_completion_claimed'] is False and event['exact_effective_clock_claimed'] is False
         and datetime.fromisoformat(event['tender_expiration_new_york'])
             <= datetime.fromisoformat(event['filing_accepted_new_york'])
             < datetime.fromisoformat(event['close_new_york'])
         and datetime.fromisoformat(event['close_new_york']).date().isoformat() == event['session'],
         'CLOSE_FACTS_INTRADAY_COMPLETION_AVAILABLE_BY_CLOSE_NOT_PREOPEN')
    need(term['kind'] == 'CASH_PLUS_STOCK' and term['session'] == event['session']
         and term['security_id'] == event['security_id'] and term['cash_per_share'] == 30.
         and term['exchange_ratio'] == '0.03002' and term['cash_in_lieu_price_per_delivered_share'] is None
         and term['entitlement_aggregation'] == 'HOLDER'
         and (term['delivered_security_id'], term['delivered_ticker'], term['delivered_issuer_id'])
             == tuple(event['delivered_witness'][k] for k in ('security_id', 'ticker', 'issuer_id')),
         'CLOSE_FACTS_EXACT_ORDINARY_CASH_STOCK_WITHOUT_CIL_ESTIMATE')
    for name, expected in value['inherited_sources'].items():
        need(sha((HERE / name).read_bytes()) == expected, 'CLOSE_FACTS_ALL_247_ADOPTED_SOURCE_BYTES_UNCHANGED')
    return value


def evidence(root):
    return [dict(reference=STEM + name, sha256=sha((HERE / name).read_bytes()),
                 description='Exact completed-merger closing scope contract or implementation.')
            for name in (CONTRACT, *IMPLEMENTATIONS)] + [dict(reference=STEM + 'private/1',
                sha256=sha((Path(root) / PRIVATE).read_bytes()),
                description='Complete actual source witnesses, native term, provider rows and recognition quote absence.')]


def validate_payload(payload, value):
    event = value['event'];rows = payload['source_witnesses']
    need(payload['schema'] == 'research.guarded-close-conversion-private/1' and payload['contract'] == value
         and payload['native_term'] == event['native']
         and payload['actual_member_rows_read'] == value['source_member']['all_rows']
         and payload['recognition_source_quotes'] == [] and payload['source_metadata_unchanged'] is True
         and payload['owned_settlement_model_selected'] is False and len(rows) == 2,
         'CLOSE_FACTS_FULL_ACTUAL_PRIVATE_SOURCE_BOUNDARY')
    indexed = {(v['session'], v['security_id']): v for v in rows}
    need(len(indexed) == 2, 'CLOSE_FACTS_TWO_DISTINCT_ACTUAL_WITNESSES')
    for witness in (event['source_witness'], event['delivered_witness']):
        require_witness(indexed[witness['session'], witness['security_id']], witness)
    provider = payload['provider_rows'];expected = value['provider_rows_proof']
    need(digest(provider) == expected['rows_sha256']
         and [digest(v) for v in provider] == expected['selected_row_sha256']
         and all(v['date'] == event['native_session'] and event['ticker'] in (v['ticker'], v['contraticker'])
                 for v in provider), 'CLOSE_FACTS_EVERY_PHYSICAL_PROVIDER_PREIMAGE')
    return payload


def hydrate(root, out):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.bundle import axis
    value = contract();event = value['event'];sid = event['security_id'];day = event['session']
    dates = axis();need(dates[dates.index(event['native_session']) + 1] == day,
                       'CLOSE_FACTS_EXACT_ADJACENT_TRADING_SESSIONS')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    native, = [v for v in actions.terminal.get(event['native_session'], ()) if v.security_id == sid]
    need(asdict(native) == event['native'] and digest(asdict(native)) == event['native_term_sha256']
         and not native.completeness(0)[0], 'CLOSE_FACTS_ACTUAL_INCOMPLETE_NATIVE_TERM')
    need(not any(v.security_id == sid for v in actions.terminal.get(day, ())),
         'CLOSE_FACTS_NO_UNDECLARED_EFFECTIVE_INPUT')
    wanted = {(v['session'], v['security_id']): v for v in (event['source_witness'], event['delivered_witness'])}
    found = {};conflicts = [];count = 0;member = value['source_member']
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        info = archive.getinfo(member['member'])
        need(info.file_size == member['gzip_bytes'] and info.CRC == member['zip_crc32'],
             'CLOSE_FACTS_AUTHENTICATED_ARCHIVE_MEMBER_METADATA')
        for row in inputs._archive_rows(archive, member['member']):
            count += 1;key = row['session'], row['security_id']
            if key in wanted:
                need(key not in found, 'CLOSE_FACTS_UNIQUE_SOURCE_WITNESS')
                require_witness(row, wanted[key]);found[key] = row
            if key == (day, sid): conflicts.append(row)
    need(set(found) == set(wanted) and count == member['all_rows'] and not conflicts,
         'CLOSE_FACTS_ENTIRE_SOURCE_MEMBER_AND_RECOGNITION_QUOTE_ABSENCE')
    raw = (Path(root) / 'provider-source/SHARADAR_ACTIONS.zip').read_bytes();require_alias_archive(raw)
    provider = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                provider.extend(v for v in csv.DictReader(io.TextIOWrapper(stream, encoding='utf8', newline=''))
                    if v['date'] == event['native_session'] and event['ticker'] in (v['ticker'], v['contraticker']))
    payload = dict(schema='research.guarded-close-conversion-private/1', contract=value,
        source_witnesses=[found[k] for k in sorted(found)], native_term=asdict(native),
        provider_rows=provider, actual_member_rows_read=count, recognition_source_quotes=conflicts,
        source_metadata_unchanged=True, owned_settlement_model_selected=False)
    validate_payload(payload, value);save(Path(out) / PRIVATE, payload)
    return payload


def expected_repair(root, predecessor):
    value = contract();event = value['event']
    validate_payload(json.loads((Path(root) / PRIVATE).read_bytes()), value)
    return dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=predecessor,
        source_evidence=evidence(root), suppress=[dict(session=event['native_session'],
            security_id=event['security_id'], term_sha256=event['native_term_sha256'])],
        add=[deepcopy(event['added'])])


def build(cp, root, out):
    hosted();value = contract();event = value['event']
    need(cp['source_cursor'] < event['native_session'], 'CLOSE_FACTS_OWN_UNCONSUMED_PARENT')
    require_absent(cp['run']['state']['wealth_core'], cp['run']['state']['pending'], [event['security_id']])
    require_intents(cp['run']['state']['last_evidence']['wealth_core']['intents'], [event['security_id']])
    preflight = SixModelPreflight(cp, root)
    report = preflight.analyze(cp, root, dict(schema=value['schema'], terms=[event]))
    require_disjoint(report);save(Path(out) / 'close-collision-preflight.json', report)
    hydrate(root, out)
    predecessor = cp['run']['checkpoint_sha256'];body = expected_repair(out, predecessor)
    path = Path(out) / OVERLAY
    save(path, dict(schema=SCHEMA, predecessor_checkpoint_sha256=predecessor,
        scope=SCOPE, require_unowned_and_unordered=True, require_no_entry_intents=True,
        morning_settlement_claimed=False, canonical_repair=body, source_evidence=evidence(out)))
    obj = parse(path, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=predecessor,
                expected_repair=body, expected_evidence=evidence(out))
    for cursor, pred in ((cp['source_cursor'], '0'*64), (event['native_session'], predecessor)):
        try: parse(path, resume_session=cursor, predecessor_checkpoint_sha256=pred,
                   expected_repair=body, expected_evidence=evidence(out))
        except ValueError: pass
        else: raise ValueError('REFUSED_CLOSE_FACTS_WRONG_PREDECESSOR_OR_CONSUMED_SESSION')
    return value, obj, path
