"""Profile a sanitized ACTIONS JSON/JSONL export without network access.

Usage: ``python -m tools.sentinel_actions_profile fixture.jsonl``
The output is counts by action type only; source rows and request metadata are
never echoed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sentinel.feed.action_source import multiplicity_profile


def _load(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    value = json.loads(text)
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("input must be a JSON array of objects or JSONL objects")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(multiplicity_profile(_load(args.source)),
                     sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
