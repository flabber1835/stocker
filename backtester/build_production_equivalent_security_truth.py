#!/usr/bin/env python3
"""Build a production-equivalent historical security-type truth ledger.

This is an economic-state reconstruction tool. It may use later evidence to
establish what security type was factually true on an earlier historical date.
It must never use future returns, rank, strategy outcome, survival, or later
index membership to choose a classification.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

COMMON_TOKENS = ('Common Stock', 'Common Stock Primary Class', 'Common Stock Secondary Class')
NON_COMMON_TOKENS = ('Preferred Stock', 'Warrant')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def split_interval(first: str, last: str, corrections: list[dict]) -> list[tuple[str,str,dict|None]]:
    if not corrections:
        return [(first, last, None)]
    # Corrections are required to cover complete intervals only when they overlap.
    # ISO dates permit lexical ordering.
    points = []
    cursor = first
    for row in sorted(corrections, key=lambda r: r['effective_first_session']):
        a, b = row['effective_first_session'], row['effective_last_session']
        if b < first or a > last:
            continue
        a = max(a, first); b = min(b, last)
        if cursor < a:
            from datetime import date, timedelta
            prev = (date.fromisoformat(a) - timedelta(days=1)).isoformat()
            points.append((cursor, prev, None))
        points.append((a, b, row))
        from datetime import date, timedelta
        cursor = (date.fromisoformat(b) + timedelta(days=1)).isoformat()
    if cursor <= last:
        points.append((cursor, last, None))
    return [(a,b,r) for a,b,r in points if a <= b]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', required=True, type=Path)
    p.add_argument('--reviewed', required=True, type=Path)
    p.add_argument('--corrections', required=True, type=Path)
    p.add_argument('--worklist', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args(); args.output.mkdir(parents=True, exist_ok=True)

    base = read_csv(args.base); reviewed = {r['security_id']: r for r in read_csv(args.reviewed)}
    corrections = {}
    for row in read_csv(args.corrections): corrections.setdefault(row['security_id'], []).append(row)
    work = {r['security_id']: r for r in read_csv(args.worklist)}
    assert len(base) == 1751 and len(reviewed) == 18

    truth = []; queue = []
    for row in base:
        sid = row['security_id']; first = row['unknown_first_session']; last = row['unknown_last_session']
        if row['classification'] in ('common','non_common'):
            baseline = row['classification']; authority = 'VENDOR_CATEGORY_PLUS_EPISODE_IDENTITY'
            evidence_kind = row['category']; evidence = row['reason']
        else:
            rr = reviewed[sid]; baseline = rr['classification']; authority = 'MANUAL_HISTORICAL_REVIEW'
            evidence_kind = rr['evidence_kind']; evidence = rr['evidence_summary']
        for a,b,corr in split_interval(first,last,corrections.get(sid, [])):
            classification = corr['classification'] if corr else baseline
            source = 'AUTHORITATIVE_HISTORICAL_INTERVAL_CORRECTION' if corr else authority
            truth.append({
                'security_id': sid, 'ticker': row['ticker'], 'effective_first_session': a,
                'effective_last_session': b, 'classification': classification,
                'truth_source': source, 'vendor_category': row['category'],
                'evidence_kind': corr['evidence_kind'] if corr else evidence_kind,
                'evidence_url': corr['evidence_url'] if corr else (reviewed.get(sid,{}).get('evidence_url','')),
                'evidence_summary': corr['evidence_summary'] if corr else evidence,
                'outcome_information_used': 'NO',
            })
        w = work.get(sid, {})
        contacts = sum(int(w.get(k) or 0) for k in ('pending_sessions','held_sessions','durable_ranked_sessions','recent_leadership_sessions'))
        cusips = [x for x in row.get('cusips','').split() if x]
        category = row['category']
        category_clear = any(tok in category for tok in COMMON_TOKENS + NON_COMMON_TOKENS)
        conflict = row['classification'] == 'unknown'
        multi_identity = len(cusips) > 1
        if conflict or multi_identity or not category_clear:
            if int(w.get('held_sessions') or 0) or int(w.get('pending_sessions') or 0): priority='P0_HELD_OR_PENDING'
            elif int(w.get('durable_ranked_sessions') or 0): priority='P1_DURABLE_RANKED'
            elif int(w.get('recent_leadership_sessions') or 0): priority='P2_LEADERSHIP'
            else: priority='P3_RANKING_OR_BASE'
            queue.append({
                'security_id': sid,'ticker':row['ticker'],'priority':priority,'current_truth':baseline,
                'vendor_category':category,'cusips':row.get('cusips',''),'base_disposition':row['disposition'],
                'held_sessions':int(w.get('held_sessions') or 0),'pending_sessions':int(w.get('pending_sessions') or 0),
                'durable_ranked_sessions':int(w.get('durable_ranked_sessions') or 0),
                'recent_leadership_sessions':int(w.get('recent_leadership_sessions') or 0),
                'eligible_sessions':int(w.get('eligible_sessions') or 0),
                'reason':';'.join(x for x,flag in [('MANUAL_CONFLICT',conflict),('MULTIPLE_CUSIPS',multi_identity),('NONSTANDARD_CATEGORY',not category_clear)] if flag),
                'status':'REQUIRES_FACTUAL_CONTRADICTION_REVIEW'
            })

    truth.sort(key=lambda r:(r['security_id'],r['effective_first_session']))
    queue.sort(key=lambda r:(r['priority'], -r['held_sessions'], -r['durable_ranked_sessions'], r['ticker']))
    write_csv(args.output/'production-equivalent-security-truth-v1.csv', truth,
              ['security_id','ticker','effective_first_session','effective_last_session','classification','truth_source','vendor_category','evidence_kind','evidence_url','evidence_summary','outcome_information_used'])
    write_csv(args.output/'production-equivalent-security-truth-review-queue.csv', queue,
              ['security_id','ticker','priority','current_truth','vendor_category','cusips','base_disposition','held_sessions','pending_sessions','durable_ranked_sessions','recent_leadership_sessions','eligible_sessions','reason','status'])
    summary = {
        'schema':'champion.production-equivalent-security-truth/1','security_count':len(base),
        'truth_interval_count':len(truth),'review_queue_count':len(queue),
        'classification_intervals':{k:sum(r['classification']==k for r in truth) for k in ('common','non_common')},
        'manual_reviewed_security_count':len(reviewed),'historical_correction_rows':sum(len(v) for v in corrections.values()),
        'queue_by_priority':{p:sum(r['priority']==p for r in queue) for p in ('P0_HELD_OR_PENDING','P1_DURABLE_RANKED','P2_LEADERSHIP','P3_RANKING_OR_BASE')},
        'contract':'PRODUCTION_EQUIVALENT_CLASSIFICATION_CONTRACT.md',
        'future_outcome_information_permitted':False,
        'status':'TRUTH_HYPOTHESIS_REVIEW_QUEUE_OPEN' if queue else 'TRUTH_LEDGER_CLOSED',
        'source_sha256':{'base':sha(args.base),'reviewed':sha(args.reviewed),'corrections':sha(args.corrections),'worklist':sha(args.worklist)}
    }
    (args.output/'SUMMARY.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    (args.output/'SHA256SUMS.txt').write_text(''.join(f"{sha(x)}  {x.name}\n" for x in sorted(args.output.iterdir()) if x.is_file() and x.name!='SHA256SUMS.txt'))
    print(json.dumps(summary,sort_keys=True))
    return 0

if __name__ == '__main__': raise SystemExit(main())
