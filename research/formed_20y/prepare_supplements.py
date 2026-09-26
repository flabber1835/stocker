"""Create a new source-bound research supplement file; never modify prior input."""
import argparse
import hashlib
import json
from pathlib import Path

BASE_SHA256 = '307b3ff1bed7b3a0a9e7a5420429eae546af3642ce08be07b8dc92c25c10d0ae'


def prepare(base: Path, output: Path):
    raw = base.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise ValueError('retained supplement bytes changed')
    rows = json.loads(raw)
    events = [json.loads(Path(__file__).with_name(name).read_text()) for name in
              ('lvnta-2018-gliba-supplement.json',)]
    ids = {row['id'] for row in rows}
    keys = {(row.get('effective_session'), row['security_id'], row.get('child_security_id'))
            for row in rows}
    if any(event['id'] in ids or (event['effective_session'], event['security_id'],
                                  event.get('child_security_id')) in keys
           for event in events):
        raise ValueError('supplemental event already exists; independent reconciliation required')
    event_keys = {(event['effective_session'], event['security_id'],
                   event.get('child_security_id')) for event in events}
    if len({event['id'] for event in events}) != len(events) or len(event_keys) != len(events):
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
