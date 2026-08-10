"""Deployment doc assertions — HOST ONLY, deliberately outside tests/sentinel.

`scripts/sentinel-certify.sh` step 5 runs `tests/sentinel` INSIDE the certified
image and treats any SKIP as a certification failure. `docs/` is not copied into
that image and should not be: the image is the artefact, and prose about how to
launch it is not part of what is being certified.

So a documentation assertion living under tests/sentinel has only bad options in
there — fail because the file is absent, or skip and fail the no-skip rule. It
belongs in the host suite, which is where documentation drift is a real risk and
where the file actually exists.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "sentinel-deployment.md"


def test_the_certified_launch_is_documented_as_no_build():
    """After a freeze the manifest already names the engine; rebuilding at
    launch can only produce a different artefact, which the finalizer refuses
    three hours later."""
    body = DOC.read_text()
    assert "--no-build" in body
    assert "--start" in body


def test_the_interval_scoped_manifest_is_documented():
    """Selecting the newest manifest by mtime compares against whatever
    certification ran last, which may cover an unrelated window."""
    body = DOC.read_text()
    assert "--manifest" in body
    assert "mtime" in body
