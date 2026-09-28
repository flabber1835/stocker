"""Measure count retention separately from byte capacity, using temporary files."""
import json
from pathlib import Path
import tempfile

from sentinel.feed import acquisition_work
from tools.acquisition_resources.measurement import disk


def probe(root):
    root.mkdir(parents=True, exist_ok=True)
    for index in range(65):
        acquisition_work.save_cached(root / f"{index:03}.zip", b"s" * 4096)
    small = disk(root)
    for path in sorted(root.glob("*.zip")):
        acquisition_work.save_cached(path, b"L" * 16384)
        assert acquisition_work.read_cached(path) == b"L" * 16384
    return dict(small=small, larger=disk(root))


def main():
    with tempfile.TemporaryDirectory(prefix="acquisition-cache-capacity-") as directory:
        print(json.dumps(probe(Path(directory)), sort_keys=True))


if __name__ == "__main__":
    main()
