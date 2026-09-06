#!/usr/bin/env python3
"""Validate a factual type-review batch and expose the full review coverage.

Classifications depend only on the pinned legal-fact docket. Path observations
are consumed separately to prioritize review. This is an incremental audit;
its output is never a final certification or a complete historical identity proof.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

FACTS_SHA256 = 'b08d6e4b92bb0a0e106927e15c6ea7ef5f8f0ffec3174c4aacc93bbd60cde517'
BASE_SHA256 = '1391630785c56daa2c4665abe792dd7b06d3697b47e2224edd380737fef133ab'
WORKLIST_SHA256 = 'da303f6a74f28dc5e47bb50ec6a0ec0d7268867154cd208242c054fc4ab29362'
DEFAULT_FACTS = Path(__file__).resolve().parent / 'data/champion-security-truth-factual-batch-v2.json'
ALLOWED_HOSTS = {'www.sec.gov', 'depositaryreceipts.citi.com'}
COUNTS = ('held_sessions', 'pending_sessions', 'durable_ranked_sessions', 'recent_leadership_sessions', 'eligible_sessions')
CASE_FIELDS = {'security_id', 'ticker', 'cusips', 'effective_first_session', 'effective_last_session',
               'previous_classification', 'classification', 'legal_security_type', 'source_ids',
               'decision_basis', 'outcome_information_used', 'adjudication', 'interval_reason'}
RULES = {'ADS_ON_PREFERRED_SHARES': 'non_common', 'LIMITED_PARTNERSHIP_COMMON_UNITS': 'non_common'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def unique(rows: list[dict], key: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        value = row[key]
        if value in result:
            raise ValueError(f'duplicate {key}: {value}')
        result[value] = row
    return result


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('source must be an approved HTTPS primary-source URL')
    if parsed.hostname == 'www.sec.gov' and not parsed.path.startswith('/Archives/edgar/data/'):
        raise ValueError('SEC source must be an EDGAR filing')


def validate_document(doc: dict, base: dict[str, dict]) -> dict[str, dict]:
    if doc.get('schema') != 'champion.security-truth-factual-batch/2':
        raise ValueError('wrong factual-batch schema')
    if doc.get('future_outcome_information_permitted') is not False:
        raise ValueError('future outcomes are prohibited')
    if doc.get('scope') != 'CANONICAL_UNKNOWN_SECURITY_TYPE_SEAM_ONLY':
        raise ValueError('unsupported classification scope')
    if doc.get('status') != 'PARTIAL_FACTUAL_AUDIT_NOT_CERTIFIED':
        raise ValueError('incremental audit must remain uncertified')
    if doc.get('evidence_timing_policy') != 'LATER_AUTHORITY_MAY_ESTABLISH_EARLIER_FACT':
        raise ValueError('wrong factual-truth contract')
    if doc.get('classification_rules') != RULES:
        raise ValueError('legal security-class policy drift')
    sources = unique(doc['sources'], 'source_id')
    for source in sources.values():
        validate_url(source['url'])
        if not source.get('finding') or not source.get('locator') or not source.get('document'):
            raise ValueError('primary evidence must retain finding and locator')
    cases = unique(doc['corrections'], 'security_id')
    for sid, case in cases.items():
        if set(case) != CASE_FIELDS:
            raise ValueError('unexpected or missing factual-case field')
        if sid not in base or not re.fullmatch(r'[1-9][0-9]*', sid):
            raise ValueError(f'unknown canonical security: {sid}')
        row = base[sid]
        if row['ticker'] != case['ticker']:
            raise ValueError(f'ticker/identity mismatch: {sid}')
        if case['cusips'] != sorted(set(row['cusips'].split())):
            raise ValueError(f'CUSIP inventory mismatch: {sid}')
        for field, basefield in [('effective_first_session', 'unknown_first_session'), ('effective_last_session', 'unknown_last_session')]:
            value = case[field]
            if date.fromisoformat(value).isoformat() != value or value != row[basefield]:
                raise ValueError(f'correction must match the admitted interval: {sid}')
        if case['effective_first_session'] > case['effective_last_session']:
            raise ValueError('reversed interval')
        if case['previous_classification'] != row['classification'] or case['previous_classification'] != 'common':
            raise ValueError('unexpected baseline classification')
        if RULES.get(case['legal_security_type']) != case['classification']:
            raise ValueError('legal class / classification mismatch')
        if case['decision_basis'] != 'LEGAL_SECURITY_CLASS_ONLY' or case['outcome_information_used'] is not False:
            raise ValueError('outcome-based adjudication is prohibited')
        if case['adjudication'] != 'REVIEWED_TYPE_CORRECTION' or not case['interval_reason']:
            raise ValueError('missing bounded factual decision')
        refs = case['source_ids']
        if not refs or len(refs) != len(set(refs)) or any(ref not in sources for ref in refs):
            raise ValueError('missing or duplicated evidence reference')
    if set(sources) != {ref for case in cases.values() for ref in case['source_ids']}:
        raise ValueError('unbound evidence source')
    return cases


def load_cases(facts: Path, base: dict[str, dict]) -> tuple[dict, dict[str, dict]]:
    raw = facts.read_bytes()
    if digest(raw) != FACTS_SHA256:
        raise ValueError('factual batch SHA-256 mismatch')
    doc = json.loads(raw)
    return doc, validate_document(doc, base)


def apply_to_truth(truth: list[dict], cases: dict[str, dict], sources: dict[str, dict]) -> list[dict]:
    """Apply only the reviewed unknown-seam intervals; preserve every other row."""
    result = []
    applied = Counter()
    for row in truth:
        updated = dict(row)
        sid = row['security_id']
        if sid in cases:
            case = cases[sid]
            for field in ('ticker', 'effective_first_session', 'effective_last_session'):
                if case[field] != row[field]:
                    raise ValueError('reviewed interval differs from baseline truth interval')
            if row['classification'] != case['previous_classification']:
                raise ValueError('factual correction conflicts with an existing truth override')
            updated.update(classification=case['classification'], truth_source='MANUAL_PRIMARY_LEGAL_TYPE_REVIEW_V2',
                           evidence_kind=case['legal_security_type'], evidence_url=' | '.join(sources[s]['url'] for s in case['source_ids']),
                           evidence_summary=case['interval_reason'], outcome_information_used='false')
            applied[sid] += 1
        result.append(updated)
    if dict(applied) != {sid: 1 for sid in cases}:
        raise ValueError('each reviewed correction must replace exactly one admitted interval')
    return result


def priority(observed: dict) -> str:
    n = lambda k: int(observed.get(k) or 0)
    if n('held_sessions') or n('pending_sessions'):
        return 'P0_HELD_OR_PENDING'
    if n('durable_ranked_sessions'):
        return 'P1_DURABLE_RANKED'
    if n('recent_leadership_sessions'):
        return 'P2_LEADERSHIP'
    return 'P3_RANKING_OR_BASE'


def coverage(base: dict[str, dict], original_queue: dict[str, dict], work: dict[str, dict], cases: dict[str, dict]) -> list[dict]:
    """Path counts affect work priority only. They never supply a security class."""
    if not set(original_queue) <= set(base) or not set(base) <= set(work):
        raise ValueError('coverage inputs do not bind the complete canonical candidate inventory')
    rows = []
    for sid, b in base.items():
        observed = work[sid]
        p = priority(observed)
        old = original_queue.get(sid)
        reviewed = sid in cases
        required = old is not None or p == 'P0_HELD_OR_PENDING' or reviewed
        reasons = ([old['reason']] if old else [])
        if old is None and p == 'P0_HELD_OR_PENDING':
            reasons.append('HELD_OR_PENDING_OMITTED_FROM_INITIAL_HEURISTIC_QUEUE')
        if old is None and reviewed:
            reasons.append('FACTUAL_TYPE_DEFECT_OMITTED_FROM_INITIAL_HEURISTIC_QUEUE')
        row = dict(security_id=sid, ticker=b['ticker'], priority=p, original_queue_member=str(old is not None).lower(),
                   review_required=str(required).lower(), status='REVIEWED_TYPE_CORRECTION' if reviewed else ('OPEN_REVIEW' if required else 'BASE_HYPOTHESIS_NOT_IN_CURRENT_REVIEW_FRONTIER'),
                   candidate_classification=b['classification'], reviewed_classification=cases[sid]['classification'] if reviewed else '',
                   cusips=b['cusips'], unknown_first_session=b['unknown_first_session'], unknown_last_session=b['unknown_last_session'],
                   reason=';'.join(reasons), path_evidence_run='34007704385', path_is_pre_correction='true')
        row.update({key: int(observed.get(key) or 0) for key in COUNTS})
        rows.append(row)
    return sorted(rows, key=lambda r: (r['priority'], -r['held_sessions'], -r['pending_sessions'], -r['durable_ranked_sessions'], r['security_id']))


def capture_sources(doc: dict, output: Path) -> list[dict]:
    """Retain raw evidence opportunistically; report blocked access explicitly.

    A blocked host is circuit-broken after the first denial or two transport
    failures. A fetch result is never used to alter an adjudication.
    """
    directory = output / 'primary-sources'
    directory.mkdir()
    blocked = {}
    failures = Counter()
    records = []
    for source in doc['sources']:
        url = source['url']
        validate_url(url)
        host = urlparse(url).hostname
        record = {'source_id': source['source_id'], 'url': url, 'review_method': source['review_method'], 'raw_bytes_retained': False}
        if host in blocked:
            record.update(status='HOST_CIRCUIT_OPEN', reason=blocked[host])
        else:
            try:
                request = Request(url, headers={'User-Agent': 'Stocker historical security-type audit m.bron01@gmail.com', 'Accept': 'text/html,application/xhtml+xml,application/xml'})
                with urlopen(request, timeout=12) as response:
                    validate_url(response.url)
                    raw = response.read(16 * 1024 * 1024 + 1)
                    if len(raw) > 16 * 1024 * 1024:
                        raise ValueError('source exceeds 16 MiB retention limit')
                    if len(raw) < 128 or b'Your Request Originates from an Undeclared Automated Tool' in raw or b'Your Request Originates from an Automated Process' in raw:
                        raise ValueError('response is empty or a SEC access-denial page')
                path = directory / (source['source_id'] + '.html.gz')
                path.write_bytes(gzip.compress(raw, mtime=0))
                record.update(status='RAW_BYTES_RETAINED', raw_bytes_retained=True, raw_sha256=digest(raw),
                              stored_path=str(path.relative_to(output)), stored_sha256=digest(path.read_bytes()), raw_size_bytes=len(raw))
                time.sleep(0.25)
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                reason = f'{type(exc).__name__}: {exc}'
                record.update(status='FETCH_FAILED', reason=reason)
                failures[host] += 1
                if isinstance(exc, HTTPError) and exc.code in (401, 403, 429) or failures[host] >= 2:
                    blocked[host] = reason
        records.append(record)
        print(f"[SOURCE] {source['source_id']} {record['status']}", flush=True)
    write_json(output / 'primary-source-retention.json', records)
    return records


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'truth', 'queue', 'worklist', 'output'):
        p.add_argument('--' + name, required=True, type=Path)
    p.add_argument('--facts', type=Path, default=DEFAULT_FACTS)
    p.add_argument('--capture-sources', action='store_true')
    args = p.parse_args()
    if digest(args.base.read_bytes()) != BASE_SHA256 or digest(args.worklist.read_bytes()) != WORKLIST_SHA256:
        raise ValueError('pinned candidate or original-path input hash mismatch')
    base = unique(read_csv(args.base), 'security_id')
    original = unique(read_csv(args.queue), 'security_id')
    work = unique(read_csv(args.worklist), 'security_id')
    truth = read_csv(args.truth)
    if len(base) != 1751 or len(original) != 715 or len(truth) != 1752:
        raise ValueError('unexpected retained checkpoint dimensions')
    doc, cases = load_cases(args.facts, base)
    if len(cases) != 7:
        raise ValueError('the frozen V2 correction batch contains exactly seven securities')
    revised = apply_to_truth(truth, cases, unique(doc['sources'], 'source_id'))
    inventory = coverage(base, original, work, cases)
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise ValueError('audit output directory must be fresh')
    write_json(args.output / 'factual-batch.json', doc)
    write_csv(args.output / 'production-equivalent-security-truth-v2.csv', revised, list(truth[0]))
    write_csv(args.output / 'complete-candidate-coverage-v2.csv', inventory, list(inventory[0]))
    frontier = [r for r in inventory if r['review_required'] == 'true']
    residual = [r for r in frontier if r['status'] == 'OPEN_REVIEW']
    write_csv(args.output / 'expanded-review-frontier-v2.csv', frontier, list(inventory[0]))
    write_csv(args.output / 'remaining-review-queue-v2.csv', residual, list(inventory[0]))
    p0 = [r for r in inventory if r['priority'] == 'P0_HELD_OR_PENDING']
    write_csv(args.output / 'all-held-or-pending-type-cases-v2.csv', p0, list(inventory[0]))
    summary = dict(schema='champion.security-truth-audit/2', status='PARTIAL_FACTUAL_AUDIT_NOT_CERTIFIED',
                   security_count=len(base), truth_interval_count=len(revised), original_queue_count=len(original),
                   factual_type_corrections=len(cases), corrected_tickers=sorted(c['ticker'] for c in cases.values()),
                   corrections_omitted_from_original_queue=sum(sid not in original for sid in cases),
                   original_queue_cases_type_corrected=sum(sid in original for sid in cases),
                   original_queue_cases_still_open=len(set(original) - set(cases)),
                   held_or_pending_count=len(p0), held_or_pending_omitted_from_original_queue=sum(r['original_queue_member'] == 'false' for r in p0),
                   held_or_pending_still_open=sum(r['status'] == 'OPEN_REVIEW' for r in p0),
                   expanded_frontier_count=len(frontier), remaining_expanded_frontier_count=len(residual),
                   remaining_priority_counts=dict(sorted(Counter(r['priority'] for r in residual).items())),
                   evidence_source_count=len(doc['sources']), factual_batch_sha256=FACTS_SHA256,
                   original_path_worklist_sha256=WORKLIST_SHA256, source_classification_does_not_depend_on_path=True,
                   later_authority_for_earlier_legal_facts_permitted=True, future_outcome_information_permitted=False,
                   primary_source_bytes_complete=False,
                   limitations=['The 715-case queue was a heuristic subset; the complete candidate inventory contains 1751 securities.',
                                'This batch reviews seven demonstrated type defects. Other factual and historical-identity cases remain open.',
                                'Priority counts come from run 34007704385 and must be recomputed after the changed execution path.',
                                'The UAN new-CUSIP event document remains an identity-retention follow-up; LP-unit type is established by issuer filings.',
                                'The overlay applies only at canonical unknown-type seams; known metadata and all economic controls remain unchanged.'])
    if args.capture_sources:
        retained = capture_sources(doc, args.output)
        summary['primary_source_bytes_complete'] = all(r['raw_bytes_retained'] for r in retained)
        summary['primary_sources_raw_retained'] = sum(r['raw_bytes_retained'] for r in retained)
        summary['primary_sources_raw_unavailable'] = sum(not r['raw_bytes_retained'] for r in retained)
    write_json(args.output / 'SUMMARY.json', summary)
    write_json(args.output / 'INPUTS.json', {name: {'name': getattr(args, name).name, 'sha256': digest(getattr(args, name).read_bytes())} for name in ('base', 'truth', 'queue', 'worklist', 'facts')})
    write_json(args.output / 'SHA256.json', {str(f.relative_to(args.output)): digest(f.read_bytes()) for f in sorted(args.output.rglob('*')) if f.is_file()})
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
