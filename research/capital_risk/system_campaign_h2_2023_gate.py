"""Canonical cash packets with actual frozen recognition-date quote absence."""
from pathlib import Path
import zipfile

from full_system_core import hosted
from full_system_benchmark import need, save


def require_absent(actual, catalog):
    need(catalog['same_day_quote_claims'] == [] and actual == {},
         'H22023_NO_UNDECLARED_RECOGNITION_DAY_QUOTES')


def qualify(out, calendar, objects, loaded, request):
    hosted()
    from research.pooled_input_support import inputs
    catalog = calendar.catalog
    terms = {(t['added']['session'], t['security_id']): t for t in catalog['terms']}
    need(len(terms) == len(catalog['terms']) == 7,
         'H22023_EXACT_SEVEN_DISTINCT_RECOGNITION_TERMS')
    calendar.qualify(loaded, objects, out / 'h2-2023-cash-calendar-qualification.json',
                     packet_source_sha256=request['qualified_packet_source_sha256'])
    actual = {}
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, _ in terms}):
            for row in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz'):
                key = row['session'], row['security_id']
                if key not in terms:
                    continue
                need(key not in actual, 'H22023_UNIQUE_ACTUAL_RECOGNITION_QUOTE')
                actual[key] = row
    require_absent(actual, catalog)
    save(out / 'h2-2023-recognition-quote-qualification.json', dict(
        status='ACTUAL_FROZEN_RECOGNITION_QUOTES_ABSENT', events=len(terms),
        retained_input_descriptors=len(objects), actual_recognition_rows=actual,
        full_original_source_scanned=True, no_quotes_or_clocks_changed=True,
        financial_sessions_advanced=0, production_contacted=False))
