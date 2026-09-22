"""Reconstruct the accepted retry lineage without editing any source segment.

For predecessor retries the latest numbered segment owns each date. Segment 044
is accepted only through July 6 (before its superseded FDO input); 045 owns the
continuation. Segment 047 is accepted only through January 28, 2016; exploratory
segments 048-051 are excluded and corrected segment 052 owns January 29 onward.
The later explicit cuts discard state that advanced across incomplete held
terminal events. Accepted rows must be non-overlapping and contiguous. The
independent verifier checks session coverage, NAV continuity, final holdings
and checkpoint session count. Selection never uses performance.
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
    parser.add_argument('--last-segment', type=int, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('preserve existing verification series')
    roots = [args.root / 'economic-replay-60m-20260921',
             args.root / 'economic-replay-merged-da7b64a9']
    paths = [p for root in roots for p in sorted(root.glob('segment-*/daily.jsonl'))]
    current = args.root / 'economic-replay-merged-ee23c894'
    if args.last_segment != 84:
        raise ValueError('final reviewed lineage ends at segment 084')
    accepted = [
        (44, '2015-07-06'), (45, None), (47, '2016-01-28'),
        *[(n, None) for n in range(52, 73)],
        (76, '2023-02-01'), (77, '2023-08-14'),
        (78, '2025-02-14'), (82, '2025-05-06'),
        (83, '2025-09-25'), (84, None),
    ]
    paths += [current / f'segment-{n:03d}/daily.jsonl' for n, _ in accepted]
    cut_by_path = {current / f'segment-{n:03d}/daily.jsonl': cut
                   for n, cut in accepted if cut is not None}
    if any(not path.exists() for path in paths):
        raise ValueError('accepted segment is absent')
    daily, owners, sources = {}, {}, []
    overlaps = different = excluded = 0
    for path in paths:
        raw = path.read_bytes()
        sources.append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
                        'bytes': len(raw)})
        for line in raw.decode().splitlines():
            row = json.loads(line)
            day = row['date']
            if day > cut_by_path.get(path, '9999-12-31'):
                excluded += 1
                continue
            if path.parent.parent == current and int(path.parent.name.removeprefix('segment-')) >= 52:
                if daily and day <= max(daily):
                    raise ValueError('corrected continuation overlaps accepted history')
            if day in daily:
                overlaps += 1
                different += row != daily[day]
            daily[day], owners[day] = row, str(path)
    ordered = [daily[day] for day in sorted(daily)]
    for previous, row in zip(ordered, ordered[1:]):
        assert abs(Decimal(row['economics']['previous_strategy_nav']) -
                   Decimal(previous['nav'])) < Decimal('1e-15'), row['date']
    final = current / f'segment-{args.last_segment:03d}'
    pointer = json.loads((final / 'latest-checkpoint.json').read_text())
    assert pointer['last_session'] == ordered[-1]['date']
    args.output.mkdir(parents=True)
    (args.output / 'daily.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in ordered), encoding='utf-8', newline='\n')
    shutil.copyfile(final / 'latest-checkpoint.json', args.output / 'latest-checkpoint.json')
    provenance = {'policy': __doc__, 'sources': sources, 'sessions': len(ordered),
                  'overlapping_rows': overlaps, 'different_overlap_rows': different,
                  'superseded_rows_excluded': excluded,
                  'last_segment': args.last_segment, 'owner_by_date': owners}
    (args.output / 'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in provenance.items() if k not in ('sources', 'owner_by_date')}))


if __name__ == '__main__':
    main()
