"""Exact reversal of reviewed opening changes for historical architecture checks."""
import hashlib
import json
from pathlib import Path


def predecessor(module, raw):
    # Reconstruct the verified pre-opening source for the older architecture
    # checks, including their original guard-removal tests.
    fixture = Path(__file__).with_name("parallel-opening-predecessor.json")
    data = fixture.read_bytes()
    assert hashlib.sha256(data).hexdigest() == "537ed6dc0bafa9ef23f3824be2163b2035761d24d1b942ec4b96bb87e641e757"
    inventory = json.loads(data)
    assert inventory["predecessor"] == "43c9691fc4a8ae5c414c590a8f374f56c108abf8"
    record = inventory["modules"].get(module)
    if record is None:
        return raw
    assert hashlib.sha256(raw).hexdigest() == record["after"], "unreviewed opening source"
    lines = raw.splitlines(keepends=True)
    for start, stop, old in reversed(record["edits"]):
        lines[start:stop] = [old.encode("utf-8")]
    before = b"".join(lines)
    assert hashlib.sha256(before).hexdigest() == record["before"], "opening predecessor differs"
    return before
