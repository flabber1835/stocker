"""Compare retained source bindings; reuse evidence only at its stated scope."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    checks = []
    for path in sorted((ROOT/'audit/economic_399').rglob('source-provenance.json')):
        doc = json.loads(path.read_text())
        files = next((doc[key] for key in (
            'files', 'source_sha256', 'source_files', 'sources', 'sha256',
            'source_sha256_git_lf') if isinstance(doc.get(key), dict)), doc)
        same, changed = [], []
        for name, wanted in files.items():
            if isinstance(wanted, dict):
                wanted = wanted.get('sha256')
            if not isinstance(wanted, str) or len(wanted) != 64 or '/' not in name:
                continue
            source = ROOT/name
            actual = (hashlib.sha256(source.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                      if source.is_file() else None)
            (same if actual == wanted else changed).append(name)
        if same or changed:
            checks.append(dict(evidence=path.relative_to(ROOT).as_posix(),
                               same=same, changed=changed))
    output = Path(__file__).with_name('prior-source-comparison.json')
    output.write_bytes((json.dumps(checks, indent=2)+'\n').encode())
    for row in checks:
        print(row['evidence'], len(row['same']), 'unchanged;', len(row['changed']), 'changed')


if __name__ == '__main__':
    main()
