"""Export untrusted Git bytes for image-side authenticated compatibility proof."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

SEAMS = {'core/decision.py', 'rolling_checkpoint.py', 'rolling_daily_checkpoint.py'}


def build(*, root, revision):
    if re.fullmatch('[0-9a-f]{40}', revision) is None:
        raise ValueError('exact retained revision required')
    raw = subprocess.check_output(['git', 'archive', revision, 'sentinel'], cwd=root, timeout=60)
    files, sources = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for item in archive:
            if item.isfile() and item.name.startswith('sentinel/') and item.name.endswith('.py'):
                path = item.name[len('sentinel/'):]
                value = archive.extractfile(item).read()
                files[path] = hashlib.sha256(value).hexdigest()
                if path in SEAMS:
                    sources[path] = value.decode('utf-8')
    if not files:
        raise ValueError('retained revision has no Sentinel sources')
    return {'schema': 'sentinel.retained-source-manifest/1', 'revision': revision,
            'files': files, 'seam_sources': sources}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    print(json.dumps(build(root=Path.cwd(), revision=args.revision), sort_keys=True))
