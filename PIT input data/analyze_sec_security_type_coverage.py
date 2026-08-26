#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEC_DIR = ROOT / 'sec'
PIT_DIR = ROOT / 'PIT input data'
TICKERS_ZIP = ROOT / 'sharadar' / 'SHARADAR_TICKERS.zip'
BUYS = (
    ROOT
    / 'research'
    / 'sentinel-fastgate'
    / 'experiments'
    / '2026-08-25-pit-vs-full-c'
    / 'recovered'
    / 'terminal_issuer_corrected'
    / 'output'
    / 'executed_buys.csv'
)
MANUAL_GLOB = 'SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE*.csv'

COMMON_PATTERNS = [
    re.compile(r'\bcommon\s+(stock|shares?)\b', re.I),
    re.compile(r'\bclass\s+[a-z0-9]+\s+common\b', re.I),
    re.compile(r'\bordinary\s+shares?\b', re.I),
    re.compile(r'\bordinary\s+stock\b', re.I),
]
EXCLUDE_PATTERNS = [
    re.compile(x, re.I)
    for x in [
        r'preferred',
        r'warrant',
        r'option',
        r'restricted\s+stock\s+unit|\brsu\b',
        r'phantom',
        r'convertible',
    ]
]
COMMON_MANUAL_CLASSES = {'common', 'common_equity_adr'}
ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def norm(s):
    return (s or '').strip()


def pick(headers, names):
    c = {re.sub(r'[^a-z0-9]', '', h.lower()): h for h in headers}
    for n in names:
        k = re.sub(r'[^a-z0-9]', '', n.lower())
        if k in c:
            return c[k]


def parse_table(raw):
    text = raw.decode('utf-8-sig', errors='replace')
    first = text.splitlines()[0] if text else ''
    return csv.DictReader(
        io.StringIO(text),
        delimiter='\t' if first.count('\t') >= first.count(',') else ',',
    )


def classify_title(title):
    return (
        bool(title)
        and not any(p.search(title) for p in EXCLUDE_PATTERNS)
        and any(p.search(title) for p in COMMON_PATTERNS)
    )


def load_legacy_tickers():
    with zipfile.ZipFile(TICKERS_ZIP) as z:
        names = z.namelist()
        target = next(
            n
            for n in names
            if 'tickers' in Path(n).name.lower()
            and Path(n).suffix.lower() in {'.csv', '.tsv'}
        )
        r = parse_table(z.read(target))
        out = {}
        for row in r:
            t = norm(row.get('ticker'))
            cat = norm(row.get('category'))
            if t:
                out[t] = cat
        return out


def load_executed_buys():
    if not BUYS.exists():
        return []
    with BUYS.open(newline='', encoding='utf-8') as f:
        r = csv.DictReader(f)
        rows = []
        for row in r:
            t = norm(row.get('ticker')).upper()
            d = norm(row.get('date') or row.get('session') or row.get('entry_date'))
            if t:
                rows.append((t, d))
        return rows


def load_manual_evidence(executed_buy_pairs):
    """Load human-reviewed exact-buy evidence without weakening the PIT cutoff.

    Manual evidence is admitted only for the exact (Orion ticker, buy date) pair
    recorded in a curated evidence CSV.  A row must have a non-empty causal join
    basis, an ISO filing/evidence date strictly before the buy date, and an
    explicit verified status.  Current metadata therefore cannot silently turn
    into a historical classification, and same-session filings remain rejected.
    """
    files = sorted(PIT_DIR.glob(MANUAL_GLOB))
    by_pair = defaultdict(list)
    audit = []

    for path in files:
        with path.open(newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            required = {
                'orion_ticker',
                'buy_date',
                'classification',
                'evidence_date',
                'join_basis',
                'status',
            }
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise RuntimeError(f'{path.name}: missing manual evidence columns {sorted(missing)}')

            for line_no, row in enumerate(reader, start=2):
                ticker = norm(row.get('orion_ticker')).upper()
                buy_date = norm(row.get('buy_date'))
                classification = norm(row.get('classification')).lower()
                evidence_date = norm(row.get('evidence_date'))
                join_basis = norm(row.get('join_basis'))
                status = norm(row.get('status')).lower()
                pair = (ticker, buy_date)
                admission = 'rejected'
                reason = ''
                resolved_as = ''

                if not ticker or not buy_date:
                    reason = 'missing_pair_key'
                elif pair not in executed_buy_pairs:
                    reason = 'not_an_authoritative_executed_buy_pair'
                elif not ISO_DATE.fullmatch(buy_date):
                    reason = 'invalid_buy_date'
                elif not ISO_DATE.fullmatch(evidence_date):
                    reason = 'invalid_evidence_date'
                elif evidence_date >= buy_date:
                    reason = 'evidence_not_strictly_prebuy'
                elif not join_basis:
                    reason = 'missing_join_basis'
                elif status.startswith('verified_common'):
                    if classification not in COMMON_MANUAL_CLASSES:
                        reason = 'verified_common_status_classification_mismatch'
                    else:
                        admission = 'admitted'
                        resolved_as = 'common'
                elif status.startswith('verified_non_common'):
                    if classification in COMMON_MANUAL_CLASSES:
                        reason = 'verified_non_common_status_classification_mismatch'
                    else:
                        admission = 'admitted'
                        resolved_as = 'non_common'
                else:
                    reason = 'status_not_explicitly_verified'

                audit.append(
                    {
                        'source_file': path.name,
                        'source_line': line_no,
                        'orion_ticker': ticker,
                        'buy_date': buy_date,
                        'classification': classification,
                        'evidence_date': evidence_date,
                        'join_basis': join_basis,
                        'status': status,
                        'admission': admission,
                        'resolved_as': resolved_as,
                        'reason': reason,
                    }
                )
                if admission == 'admitted':
                    by_pair[pair].append(
                        {
                            'resolved_as': resolved_as,
                            'classification': classification,
                            'evidence_date': evidence_date,
                            'source_file': path.name,
                            'source_line': line_no,
                            'status': status,
                            'join_basis': join_basis,
                        }
                    )

    resolved = {}
    for pair, rows in by_pair.items():
        outcomes = {r['resolved_as'] for r in rows}
        if len(outcomes) != 1:
            raise RuntimeError(
                f'Contradictory admitted manual security-type classifications for {pair}: {rows}'
            )
        rows = sorted(rows, key=lambda r: (r['evidence_date'], r['source_file'], r['source_line']))
        resolved[pair] = {
            'resolved_as': rows[0]['resolved_as'],
            'classification': rows[0]['classification'],
            'evidence_date': rows[0]['evidence_date'],
            'sources': rows,
        }

    audit_path = PIT_DIR / 'SEC_SECURITY_TYPE_MANUAL_ADMISSION_AUDIT.csv'
    with audit_path.open('w', newline='', encoding='utf-8') as f:
        fields = [
            'source_file',
            'source_line',
            'orion_ticker',
            'buy_date',
            'classification',
            'evidence_date',
            'join_basis',
            'status',
            'admission',
            'resolved_as',
            'reason',
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(audit)

    return files, resolved, audit


def main():
    zips = sorted(SEC_DIR.glob('*_form345.zip'))
    if not zips:
        raise SystemExit('No SEC Form 3/4/5 archives found')

    title_counter = Counter()
    evidence = []
    first_common = {}
    archive_stats = []

    for zp in zips:
        quarter = zp.stem.replace('_form345', '')
        with zipfile.ZipFile(zp) as z:
            members = z.namelist()
            local_meta = {}
            for m in members:
                if 'submission' not in Path(m).name.lower():
                    continue
                r = parse_table(z.read(m))
                h = r.fieldnames or []
                a = pick(h, ['accession_number', 'accessionnumber', 'accession'])
                fd = pick(h, ['filing_date', 'filingdate', 'filed'])
                sy = pick(h, ['issuer_trading_symbol', 'issuertradingsymbol', 'issuersymbol'])
                cik = pick(h, ['issuer_cik', 'issuercik'])
                if not (a and fd and sy):
                    continue
                for row in r:
                    acc = norm(row.get(a))
                    sym = norm(row.get(sy)).upper()
                    filed = norm(row.get(fd))
                    c = norm(row.get(cik)) if cik else ''
                    if acc and sym and filed:
                        local_meta[acc] = (filed, sym, c)

            q_titles = q_joined = q_common = 0
            for m in members:
                base = Path(m).name.lower()
                if not ('nonderiv' in base or 'non_deriv' in base or 'non-deriv' in base):
                    continue
                r = parse_table(z.read(m))
                h = r.fieldnames or []
                a = pick(h, ['accession_number', 'accessionnumber', 'accession'])
                st = pick(h, ['security_title', 'securitytitle', 'security_title_value', 'securitytitlevalue'])
                if not (a and st):
                    continue
                for row in r:
                    acc = norm(row.get(a))
                    title = norm(row.get(st))
                    if not title:
                        continue
                    q_titles += 1
                    title_counter[title] += 1
                    meta = local_meta.get(acc)
                    if not meta:
                        continue
                    q_joined += 1
                    filed, sym, cik = meta
                    if classify_title(title):
                        q_common += 1
                        prev = first_common.get(sym)
                        if prev is None or filed < prev[0]:
                            first_common[sym] = (filed, title, cik, quarter)
                        evidence.append((sym, filed, cik, title, quarter, acc))
            archive_stats.append(
                {
                    'quarter': quarter,
                    'members': len(members),
                    'submission_rows': len(local_meta),
                    'security_title_rows': q_titles,
                    'joined_title_rows': q_joined,
                    'positive_common_rows': q_common,
                }
            )

    legacy = load_legacy_tickers()
    legacy_common = {
        t
        for t, cat in legacy.items()
        if 'common stock' in cat.lower()
        and 'warrant' not in cat.lower()
        and 'preferred' not in cat.lower()
    }
    evidence_tickers = set(first_common)
    common_covered = legacy_common & evidence_tickers

    buys = load_executed_buys()
    executed_buy_pairs = {(t, d) for t, d in buys if d}
    buy_tickers = {t for t, _ in buys}
    buy_any = buy_tickers & evidence_tickers
    manual_files, manual_resolved, manual_audit = load_manual_evidence(executed_buy_pairs)

    dated = 0
    auto_common = 0
    manual_common = 0
    manual_non_common = 0
    resolved_common = 0
    resolved_classified = 0
    gaps = []

    for t, d in buys:
        if not d:
            continue
        dated += 1
        pair = (t, d)
        ev = first_common.get(t)
        auto = bool(ev and ev[0] < d)
        manual = manual_resolved.get(pair)

        if auto and manual and manual['resolved_as'] == 'non_common':
            raise RuntimeError(
                f'Automatic common-stock evidence contradicts verified non-common manual evidence for {pair}: '
                f'auto={ev}, manual={manual}'
            )

        if auto:
            auto_common += 1
            resolved_common += 1
            resolved_classified += 1
        elif manual:
            resolved_classified += 1
            if manual['resolved_as'] == 'common':
                manual_common += 1
                resolved_common += 1
            else:
                manual_non_common += 1
        else:
            gaps.append((t, d, ev[0] if ev else ''))

    with gzip.open(
        PIT_DIR / 'SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz',
        'wt',
        newline='',
        encoding='utf-8',
    ) as f:
        w = csv.writer(f)
        w.writerow(['ticker', 'filed', 'cik', 'security_title', 'source_quarter', 'accession'])
        w.writerows(sorted(evidence, key=lambda x: (x[0], x[1], x[5])))

    with (PIT_DIR / 'SEC_SECURITY_TYPE_BUY_COVERAGE_GAPS.csv').open(
        'w', newline='', encoding='utf-8'
    ) as f:
        w = csv.writer(f)
        w.writerow(['ticker', 'buy_date', 'first_positive_common_filing'])
        w.writerows(sorted(gaps))

    admitted_audit_rows = [r for r in manual_audit if r['admission'] == 'admitted']
    rejected_audit_rows = [r for r in manual_audit if r['admission'] != 'admitted']
    manual_common_pairs = sum(1 for x in manual_resolved.values() if x['resolved_as'] == 'common')
    manual_non_common_pairs = sum(1 for x in manual_resolved.values() if x['resolved_as'] == 'non_common')

    report = {
        'archives': len(zips),
        'archive_range': [zips[0].name, zips[-1].name],
        'distinct_positive_common_tickers': len(evidence_tickers),
        'legacy_common_tickers': len(legacy_common),
        'legacy_common_ticker_coverage': len(common_covered),
        'legacy_common_ticker_coverage_pct': len(common_covered) / len(legacy_common)
        if legacy_common
        else None,
        'executed_buy_tickers': len(buy_tickers),
        'executed_buy_tickers_with_any_positive_evidence': len(buy_any),
        'executed_buy_ticker_coverage_pct': len(buy_any) / len(buy_tickers) if buy_tickers else None,
        'executed_buy_rows_with_dates': dated,
        'executed_buy_rows_auto_common_before_buy': auto_common,
        'executed_buy_rows_manual_common_before_buy': manual_common,
        'executed_buy_rows_manual_non_common_before_buy': manual_non_common,
        'executed_buy_rows_causally_covered_before_buy': resolved_common,
        'executed_buy_rows_causally_classified_before_buy': resolved_classified,
        'executed_buy_row_causal_coverage_pct': resolved_classified / dated if dated else None,
        'executed_buy_rows_not_causally_covered': len(gaps),
        'manual_evidence_files': [p.name for p in manual_files],
        'manual_evidence_rows_admitted': len(admitted_audit_rows),
        'manual_evidence_rows_rejected': len(rejected_audit_rows),
        'manual_evidence_pairs_admitted': len(manual_resolved),
        'manual_evidence_common_pairs': manual_common_pairs,
        'manual_evidence_non_common_pairs': manual_non_common_pairs,
        'top_security_titles': title_counter.most_common(100),
        'archive_stats': archive_stats,
        'classification_rule': {
            'positive_only': True,
            'automatic_rule': (
                'A symbol becomes common-stock-eligible only after a filed Form 3/4/5 '
                'non-derivative security title positively matches common/ordinary equity and '
                'matches the submission issuer trading symbol.'
            ),
            'manual_rule': (
                'Curated SEC evidence may resolve only the exact Orion ticker/buy-date pair when '
                'the row has an explicit verified status, a non-empty causal join basis, and an '
                'evidence date strictly before the buy date. Verified non-common rows resolve the '
                'pair as ineligible.'
            ),
            'decision_cutoff': 'evidence filing date must be strictly earlier than decision/buy date',
            'unknown_policy': 'unknown remains ineligible',
        },
    }
    (PIT_DIR / 'SEC_SECURITY_TYPE_COVERAGE.json').write_text(json.dumps(report, indent=2) + '\n')

    pct = lambda x: 'n/a' if x is None else f'{x:.2%}'
    md = [
        '# Orion SEC security-type coverage analysis',
        '',
        f"Archives inspected: **{len(zips)}** ({zips[0].name} through {zips[-1].name}).",
        '',
        '## Executed-buy classification coverage',
        '',
        f"- Authoritative executed-buy rows with dates: **{dated:,}**",
        f"- Automatically verified common before buy: **{auto_common:,}**",
        f"- Curated/manual verified common before buy: **{manual_common:,}**",
        f"- Curated/manual verified non-common before buy: **{manual_non_common:,}**",
        f"- Total causally classified before buy: **{resolved_classified:,}/{dated:,} ({pct(report['executed_buy_row_causal_coverage_pct'])})**",
        f"- Unresolved executed-buy rows: **{len(gaps):,}**",
        '',
        '## Automatic evidence coverage',
        '',
        f"- Positive common-stock symbols from Form 3/4/5 security-title evidence: **{len(evidence_tickers):,}**",
        f"- Legacy Sharadar common-stock symbols: **{len(legacy_common):,}**",
        f"- Legacy common-stock ticker coverage: **{len(common_covered):,}/{len(legacy_common):,} ({pct(report['legacy_common_ticker_coverage_pct'])})**",
        f"- Authoritative executed-buy tickers with any direct-symbol positive evidence: **{len(buy_any):,}/{len(buy_tickers):,} ({pct(report['executed_buy_ticker_coverage_pct'])})**",
        '',
        '## Manual evidence admission',
        '',
        f"- Curated evidence files inspected: **{len(manual_files):,}**",
        f"- Admitted exact-buy evidence rows: **{len(admitted_audit_rows):,}**",
        f"- Admitted exact-buy pairs: **{len(manual_resolved):,}**",
        f"- Rejected/non-admitted rows: **{len(rejected_audit_rows):,}**",
        '',
        '## PIT rule',
        '',
        'Automatic evidence requires a matching SEC issuer trading symbol and a positive common/ordinary-equity security title. Curated evidence is admitted only for its exact Orion ticker/buy-date pair, with an explicit verified status, a documented causal join, and an evidence date strictly earlier than the decision session. Same-day filings are not admitted without separate session-phase proof. Verified preferred, LP-unit, or other non-common instruments resolve as ineligible. Absence of evidence remains **unknown/ineligible**.',
        '',
        '## Interpretation',
        '',
        'This report is the executed-buy economic gate, not the final certification. Once unresolved executed buys reach zero, Orion still requires full candidate/session coverage against the same causal evidence boundary before a provenance-retaining `SEC_SECURITY_TYPE_PIT_ONLY` tape can be certified.',
    ]
    (PIT_DIR / 'SEC_SECURITY_TYPE_COVERAGE.md').write_text('\n'.join(md) + '\n')

    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {'top_security_titles', 'archive_stats'}},
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
