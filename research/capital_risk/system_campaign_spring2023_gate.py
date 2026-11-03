"""Actual cumulative cash packets, including PRVB's unchanged same-day quote."""
from dataclasses import asdict
from fractions import Fraction
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest
from system_campaign_sprint_facts import published_packet, qualify_packet_schema


def require_quote(row, claim):
    need((row['session'], row['security_id']) == (claim['session'], claim['security_id'])
         and digest(row) == claim['source_observation_sha256'],
         'SPRING2023_FULL_ORIGINAL_SAME_DAY_QUOTE_BYTES')


def qualify(out, calendar, objects, loaded, request):
    hosted()
    from research.pooled_input_support import inputs
    from research.pooled_input_support.inputs import Packet
    from research.pooled_vacancy_funding import backtest
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    qualify_packet_schema(Packet, request['qualified_packet_source_sha256'])
    catalog = calendar.catalog
    calendar.qualify(loaded, objects, out / 'spring2023-cash-calendar-qualification.json',
                     packet_source_sha256=request['qualified_packet_source_sha256'])
    terms = {(t['added']['session'], t['security_id']): t for t in catalog['terms']}
    claims = {(c['session'], c['security_id']): c for c in catalog['same_day_quote_claims']}
    need(len(claims) == len(catalog['same_day_quote_claims'])
         and set(claims) <= set(terms)
         and set(claims) == {('2023-04-27', '858933953652218125')},
         'SPRING2023_EXACT_DECLARED_PRVB_FROZEN_QUOTE_CONFLICT')
    actual = {}
    # Prove absence on EVERY other new recognition date too. This is a raw
    # source scan, never a substitute quote, tradeability override or new feed.
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, _ in terms}):
            for row in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz'):
                key = row['session'], row['security_id']
                if key not in terms:
                    continue
                need(key not in actual, 'SPRING2023_UNIQUE_ACTUAL_RECOGNITION_QUOTE')
                actual[key] = row
    need(set(actual) == set(claims), 'SPRING2023_NO_UNDECLARED_RECOGNITION_DAY_QUOTES')
    actions = inputs.load_actions(Path('/frozen/bundle'))
    checked = []
    for key, row in actual.items():
        day, sid = key
        t, claim = terms[key], claims[key]
        require_quote(row, claim)
        need(t['recognition_rule'] == 'CONFIRMED_PREOPEN_COMPLETION'
             and t['actual_completion_date'] == day == t['native_session']
             and t['last_trading_session'] < day,
             'SPRING2023_PRIMARY_PREOPEN_CLOCK_NOT_DELAYED_FOR_FROZEN_QUOTE')
        bar = vendor(row)
        packet = Packet(day, (bar,), {}, {}, 1., {}, tuple(actions.terminal.get(day, ())), ())
        original_sha = digest(asdict(packet))
        fixed = packet
        for obj in [*objects, loaded]:
            fixed = backtest.apply_repair(fixed, obj)
        need(digest(asdict(packet)) == original_sha and fixed.bars == packet.bars,
             'SPRING2023_ACTUAL_ORIGINAL_PACKET_AND_QUOTE_UNCHANGED')
        term, = [v for v in fixed.terminal if v.security_id == sid]
        need(asdict(term) == t['added'] and term.completeness(1)[0],
             'SPRING2023_EXACT_COMPLETE_CASH_TERM_WITH_SAME_DAY_QUOTE')
        last = calendar.rows[t['last_trading_session'], sid]
        prior = SimpleNamespace(median5={'selected': [sid]}, last_processed_session=t['last_trading_session'],
            feed={'series': {sid: {'signal_basis_anchor':
                (t['last_trading_session'], float(last['raw_close']), float(last['signal_close']))}}})
        try:
            terminal_returns.values(prior=prior, published=published_packet(packet))
        except ValueError as error:
            need(str(error) == 'incomplete leadership cash terminal: ' + sid,
                 'SPRING2023_ORIGINAL_INCOMPLETE_WITH_VALID_QUOTE_REFUSED')
        else:
            raise ValueError('REFUSED_SPRING2023_LAST_QUOTE_MUST_NOT_REPLACE_TERMS')
        values = terminal_returns.values(prior=prior, published=published_packet(fixed))
        raw_anchor, signal_anchor = map(lambda v: Fraction(str(float(v))),
                                        (last['raw_close'], last['signal_close']))
        expected = float(Fraction(str(t['added']['cash_per_share']))
                         * Fraction(str(bar.split_ratio)) * signal_anchor / raw_anchor)
        need(values == {sid: expected}, 'SPRING2023_CANONICAL_CASH_NOT_QUOTE_AS_CONSIDERATION')
        try:
            require_quote({**row, 'raw_close': row['raw_close'] + '0'}, claim)
        except ValueError:
            pass
        else:
            raise ValueError('REFUSED_SPRING2023_CHANGED_RAW_QUOTE_GUARD')
        checked.append(dict(session=day, security_id=sid,
                            source_observation_sha256=digest(row), original_packet_sha256=original_sha,
                            canonical_signal_consideration=expected, cash_per_share=t['added']['cash_per_share']))
    save(out / 'hydrated-spring2023-same-day-quotes.json', dict(
        schema='research.spring2023-same-day-source-quotes/1',
        actual_rows=[actual[k] for k in sorted(actual)], source_metadata_unchanged=True))
    save(out / 'spring2023-same-day-quote-qualification.json', dict(
        status='ACTUAL_MERGED_SAME_DAY_CASH_PACKET_QUALIFIED',
        new_catalog_events=len(terms), retained_input_descriptors=len(objects),
        actual_quote_cases=checked, all_other_recognition_day_quote_absences_verified=True,
        original_packets_and_quotes_unchanged=True, original_incomplete_terms_refused=True,
        primary_clock_not_delayed=True, changed_source_quote_falsifier_passed=True,
        financial_sessions_advanced=0, production_contacted=False))
