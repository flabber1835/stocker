"""Create a new source-bound research supplement file; never modify prior input."""
import argparse
import hashlib
import json
from pathlib import Path

BASE_SHA256 = '7c8b7da7363269d010bb4f30bdb0674563458c712a5c875568b577805919f725'


def prepare(base: Path, output: Path):
    raw = base.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise ValueError('retained supplement bytes changed')
    rows = json.loads(raw)
    events = [json.loads(Path(__file__).with_name(name).read_text()) for name in
              ('trbs-supplement.json', 'isln-supplement.json', 'lvnta-supplement.json',
               'cnqr-supplement.json')]
    identities = {(row['id'], row['security_id']) for row in rows}
    if any(any(event['id'] == row_id or event['security_id'] == security_id
               for row_id, security_id in identities) for event in events):
        raise ValueError('security already has supplemental terms; independent reconciliation required')
    if len({event['id'] for event in events}) != len(events) or len({event['security_id'] for event in events}) != len(events):
        raise ValueError('new supplement identities must be unique')
    with output.open('x', encoding='utf8') as stream:
        json.dump(rows + events, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return dict(base_sha256=BASE_SHA256, output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                retained_records=len(rows), added_records=[event['id'] for event in events])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.base, args.output), sort_keys=True))
