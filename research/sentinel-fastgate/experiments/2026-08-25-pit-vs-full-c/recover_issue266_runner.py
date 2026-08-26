#!/usr/bin/env python3
"""Recover the exact frozen A/B runner embedded in issue #266 comment 5420839934.

Research-only reproducibility helper. The comment contains a gzip|base64 payload.
The output is SHA-256 verified against the preregistered source identity before it
is written. No production code is imported or changed.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import urllib.request
from pathlib import Path

COMMENT_ID = 5420839934
EXPECTED_SHA256 = "3cb688aea8ebe5238b6b080fad012eef6bbc9df396e43252cbf336f651eb00e4"
URL = f"https://api.github.com/repos/flabber1835/stocker/issues/comments/{COMMENT_ID}"
OUT = Path(__file__).with_name("ldrc_ab_replay_20260825.py")


def main() -> None:
    req = urllib.request.Request(URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "orion-research-recovery"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)["body"]
    m = re.search(r"```text\s*(H4sI[A-Za-z0-9+/=\r\n]+?)\s*```", body, flags=re.S)
    if not m:
        raise RuntimeError("gzip/base64 payload not found in issue comment")
    payload = re.sub(r"\s+", "", m.group(1))
    source = gzip.decompress(base64.b64decode(payload))
    digest = hashlib.sha256(source).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"runner SHA mismatch: {digest} != {EXPECTED_SHA256}")
    OUT.write_bytes(source)
    print(f"recovered {OUT} bytes={len(source)} sha256={digest}")


if __name__ == "__main__":
    main()
