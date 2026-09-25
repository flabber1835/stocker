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
    event = json.loads(Path(__file__).with_name('trbs-supplement.json').read_text())
    if any(row['id'] == event['id'] or row['security_id'] == event['security_id'] for row in rows):
        raise ValueError('TRBS already has supplemental terms; independent reconciliation required')
    with output.open('x', encoding='utf8') as stream:
        json.dump(rows + [event], stream, indent=2, allow_nan=False)
        stream.write('\n')
    return dict(base_sha256=BASE_SHA256, output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                retained_records=len(rows), added_record=event['id'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.base, args.output), sort_keys=True))
