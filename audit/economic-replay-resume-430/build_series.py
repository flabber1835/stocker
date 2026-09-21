"""Reconstruct the accepted retry lineage without editing any source segment.

For predecessor retries the latest numbered segment owns each date. Segment 044
is accepted only through July 6 (before its superseded FDO input); 045 owns the
continuation. The independent verifier checks session coverage, NAV continuity,
final holdings and checkpoint session count. Selection never uses performance.
"""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('preserve existing verification series')
    roots = [args.root / 'economic-replay-60m-20260921',
             args.root / 'economic-replay-merged-da7b64a9']
    paths = [p for root in roots for p in sorted(root.glob('segment-*/daily.jsonl'))]
    current = args.root / 'economic-replay-merged-ee23c894'
    paths += [current / f'segment-{n}/daily.jsonl' for n in ('044', '045')]
    daily, owners, sources = {}, {}, []
    overlaps = different = excluded = 0
    for path in paths:
        raw = path.read_bytes()
        sources.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                        'bytes': len(raw)})
        for line in raw.decode().splitlines():
            row = json.loads(line)
            day = row['date']
            if path.parent.name == 'segment-044' and day > '2015-07-06':
                excluded += 1
                continue
            if day in daily:
                overlaps += 1
                different += row != daily[day]
            daily[day], owners[day] = row, str(path)
    ordered = [daily[day] for day in sorted(daily)]
    for previous, row in zip(ordered, ordered[1:]):
        assert abs(Decimal(row['economics']['previous_strategy_nav']) -
                   Decimal(previous['nav'])) < Decimal('1e-15'), row['date']
    pointer = json.loads((current / 'segment-045/latest-checkpoint.json').read_text())
    assert pointer['last_session'] == ordered[-1]['date']
    args.output.mkdir(parents=True)
    (args.output / 'daily.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in ordered), encoding='utf-8', newline='\n')
    shutil.copyfile(current / 'segment-045/latest-checkpoint.json', args.output / 'latest-checkpoint.json')
    provenance = {'policy': __doc__, 'sources': sources, 'sessions': len(ordered),
                  'overlapping_rows': overlaps, 'different_overlap_rows': different,
                  'superseded_044_rows_excluded': excluded, 'owner_by_date': owners}
    (args.output / 'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in provenance.items() if k not in ('sources', 'owner_by_date')}))


if __name__ == '__main__':
    main()
