"""Original cash compiler with explicit source-preimage and quote qualification."""
import csv
import io
import json
from pathlib import Path
import zipfile

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
from system_campaign_2021_completions_facts import require_alias_archive
from system_campaign_q4_cash_context import STEM
import system_campaign_cash_calendar as original

CATALOG = 'system-campaign-q4-2023-cash-calendar-terminal-facts.json'


def validate(catalog):
    need(catalog['schema'] == 'research.factual-cash-calendar-catalog/1'
         and catalog['source_research_events'] == 32 and catalog['active_unconsumed_events'] == 31
         and len(catalog['terms']) == 31 and catalog['same_day_quote_claims'] == []
         and catalog['full_provider_rows_verification_required'] is True
         and catalog['commitment_group']['reference_stem'] == STEM
         and catalog['commitment_group']['catalog_file'] == CATALOG
         and catalog['loader_sha256'] == sha(Path(original.__file__).read_bytes()),
         'Q4_EXACT_SOURCE_BOUND_31_CASH_CALENDAR_AND_ORIGINAL_LOADER')
    excluded, = catalog['excluded_consumed_events']
    need(excluded['ticker'] == 'CELL' and excluded['native_session'] == '2023-09-29'
         and excluded['recognition_session'] == '2023-10-02'
         and excluded['cross_candidate_equivalence_claimed'] is False,
         'Q4_CONSUMED_CELL_EXPLICITLY_RETAINED_OUTSIDE_THIS_SUFFIX')
    for term in catalog['terms']:
        original.validate_term(term)
        need(term['native_session'] > '2023-09-29' and term['primary_extraction']['currency'] == 'USD'
             and float(term['primary_extraction']['cash_per_ordinary_share']) == term['added']['cash_per_share'],
             'Q4_EXACT_PRIMARY_USD_COMMON_SHARE_CONSIDERATION')
    return catalog


class RecognitionTap:
    def __init__(self, catalog):
        self.expected = {v['member']: v['all_rows_read'] for v in catalog['frozen_year_member_checks']}
        self.wanted = {(v['added']['session'], v['security_id']) for v in catalog['terms']}
        self.found, self.completed = {}, {}

    def __enter__(self):
        from research.pooled_input_support import inputs
        self.inputs, self.original = inputs, inputs._archive_rows
        inputs._archive_rows = self.rows
        return self

    def rows(self, archive, member):
        need(member in self.expected and member not in self.completed,
             'Q4_ONLY_DECLARED_ONCE_ONLY_WITNESS_YEAR_SCAN')
        count = 0
        for row in self.original(archive, member):
            count += 1;key = row['session'], row['security_id']
            if key in self.wanted:
                need(key not in self.found, 'Q4_UNIQUE_ACTUAL_RECOGNITION_QUOTE')
                self.found[key] = dict(row)
            yield row
        need(count == self.expected[member], 'Q4_ACTUAL_COMPLETE_FROZEN_YEAR_AXIS')
        self.completed[member] = count

    def __exit__(self, *args):
        self.inputs._archive_rows = self.original

    def proof(self):
        need(self.completed == self.expected and self.found == {}
             and self.inputs._archive_rows is self.original,
             'Q4_COMPLETE_ACTUAL_SCANS_AND_NO_RECOGNITION_QUOTES')
        return dict(status='ALL_DECLARED_SOURCE_YEARS_COMPLETED_NO_RECOGNITION_QUOTES',
            annual_rows=self.completed, actual_recognition_quotes=[], original_rows_returned_unchanged=True,
            original_reader_restored=self.inputs._archive_rows is self.original)


def provider_rows(root, catalog):
    raw = (root / 'provider-source/SHARADAR_ACTIONS.zip').read_bytes()
    require_alias_archive(raw)
    terms = {(t['native_session'], t['ticker']): t for t in catalog['terms']}
    found = {key: [] for key in terms}
    dates = {key[0] for key in terms}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for name in archive.namelist():
            with archive.open(name) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf8', newline='')):
                    if row['date'] not in dates: continue
                    for ticker in {row['ticker'], row['contraticker']}:
                        key = row['date'], ticker
                        if key in found: found[key].append(row)
    for key, term in terms.items():
        expected = term['provider_rows_proof'];rows = found[key]
        need(expected['ticker'] == term['ticker'] and expected['session'] == term['native_session']
             and digest(rows) == expected['rows_sha256']
             and [digest(v) for v in rows] == expected['selected_row_sha256'],
             'Q4_EVERY_ACTUAL_PHYSICAL_PROVIDER_PREIMAGE')
    return {ticker: found[day, ticker] for day, ticker in sorted(found)}


def hydrate(catalog, cp, root, out):
    hosted();validate(catalog)
    need(all(cp['source_cursor'] < min(v['native_session'], v['added']['session']) for v in catalog['terms']),
         'Q4_NO_CONSUMED_EVENT_IN_ACTUAL_OWN_SUFFIX')
    calendar = original.CashCalendar(catalog)
    with RecognitionTap(catalog) as tap:
        payload = calendar.hydrate(cp, root, out)
    payload['recognition_quote_qualification'] = tap.proof()
    payload['physical_provider_rows'] = provider_rows(root, catalog)
    payload['all_physical_provider_preimages_verified'] = True
    return calendar, payload


def build(cp, old, out):
    hosted()
    from research.pooled_vacancy_funding.repair import load_repair
    path = Path(__file__).parent / CATALOG
    raw = path.read_bytes();catalog = validate(json.loads(raw))
    calendar, payload = hydrate(catalog, cp, old, out)
    group = catalog['commitment_group'];private = out / group['private_file'];save(private, payload)
    refs = {'catalog': sha(raw), 'loader': sha(Path(original.__file__).read_bytes()), 'private': sha(private.read_bytes())}
    evidence = [dict(reference=group['reference_stem']+k, sha256=v,
        description='Exact original cash compiler, primary completion calendar and full frozen witnesses.') for k,v in refs.items()]
    for term in catalog['terms']:
        evidence.extend(dict(reference=term[k], sha256=None, description=term['description'])
                        for k in ('primary_source', 'timing_source'))
    overlay = out / group['overlay_file']
    save(overlay, dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
                      source_evidence=evidence, **calendar.patch()))
    loaded = load_repair(overlay, resume_session=cp['source_cursor'],
                         predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    for cursor, predecessor in ((cp['source_cursor'], '0'*64),
            (min(v['native_session'] for v in catalog['terms']), cp['run']['checkpoint_sha256'])):
        try: load_repair(overlay, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
        except ValueError: pass
        else: raise ValueError('REFUSED_Q4_WRONG_PREDECESSOR_OR_CONSUMED_SESSION')
    return calendar, loaded, overlay
