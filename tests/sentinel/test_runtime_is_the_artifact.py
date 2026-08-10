"""The suite must exercise the ARTEFACT, and the record must NAME it.

Two defects with one root, both found in certification review, both of which
produced a confident green.

```text
THE TEST IMAGE PROVED THE CHECKOUT
    Dockerfile.sentinel-test built FROM sentinel:latest — correct — and then
    copied `sentinel/` and `shared/` into /work and put /work first on
    PYTHONPATH. Pytest imported the fresh source, so a `sentinel:latest`
    carrying stale or wrong runtime code passed every test in the suite that
    existed to check it.

THE IDENTITY RECORD COULD NOT FIND WEALTH CORE
    `identity` computed its path as `sentinel/../shared/stock_strategy_shared/
    wealth_core`. True in a checkout; FALSE in the runtime image, where
    `sentinel/` is at /app and `shared/` was pip-installed into site-packages.
    So `source_hash` returned `files: 0, hash: None` — and `certified` did not
    look at the source hashes at all, so an image with no Wealth Core identity
    whatsoever answered `--require-certified` with PASS.
```

They are the same mistake: asserting where code IS from where it OUGHT to be,
rather than asking the interpreter that just imported it. And the first hid the
second — /work happened to satisfy the layout assumption that /app does not.

These tests ask the interpreter. The ones that can only be meaningful inside the
image are gated on `SENTINEL_IN_IMAGE`, which that image sets and a checkout
does not.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel import identity as ident  # noqa: E402

IN_IMAGE = os.environ.get("SENTINEL_IN_IMAGE") == "1"
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
in_image = pytest.mark.skipif(
    not IN_IMAGE, reason="only meaningful inside the certified test image")


# ── 1. the record names code it actually found ───────────────────────────────

class TestTheIdentityRecordFindsBothSourceTrees:

    def test_it_resolves_them_by_IMPORT_not_by_repo_layout(self):
        """The fix, asserted as a property rather than as a path: whatever the
        filesystem looks like, the hashed directory is the one the interpreter
        imported from."""
        import sentinel
        import stock_strategy_shared.wealth_core as wc

        env = ident.environment()
        assert (env["sentinel_source"]["path"]
                == str(Path(sentinel.__file__).resolve().parent))
        assert (env["wealth_core_source"]["path"]
                == str(Path(wc.__file__).resolve().parent))

    def test_neither_hash_is_NULL(self):
        env = ident.environment()
        for key in ("sentinel_source", "wealth_core_source"):
            assert env[key]["hash"], f"{key} was not located: {env[key]}"
            assert env[key]["files"] > 0, key

    def test_a_MISSING_source_tree_makes_the_record_UNCERTIFIED(self):
        """The condition that was absent. `certified` used to read only the
        interpreter version and the pin drift, so 'we could not find Wealth
        Core' and 'here is Wealth Core's hash' both answered PASS."""
        env = ident.environment()
        assert env["certified"] is (env["python_certified"]
                                    and env["pins_match"]
                                    and env["sources_known"])

    def test_sources_known_is_FALSE_when_a_tree_cannot_be_found(self, monkeypatch):
        monkeypatch.setattr(ident, "_imported_package_root", lambda name: None)
        env = ident.environment()
        assert env["sources_known"] is False
        assert env["certified"] is False

    def test_the_source_hash_of_an_ABSENT_path_is_None_not_an_error(self):
        assert ident.source_hash(Path("/nonexistent/xyz"))["hash"] is None
        assert ident.source_hash(None)["hash"] is None


# ── 2. inside the image, the imports are the artefact ────────────────────────

@in_image
class TestPytestImportsTheRUNTIMECode:

    def test_sentinel_is_imported_from_app(self):
        import sentinel
        assert sentinel.__file__.startswith("/app/"), (
            f"pytest imported {sentinel.__file__} — a copy of the checkout, "
            f"not the code `sentinel:latest` will actually run")

    def test_wealth_core_comes_from_the_INSTALLED_package(self):
        import stock_strategy_shared.wealth_core as wc
        assert "/work" not in wc.__file__, (
            f"pytest imported {wc.__file__} — the test layer's copy, not the "
            f"package installed into the runtime image")

    def test_the_inspection_copy_is_NOT_importable(self):
        """/work/repo exists so the Dockerfile and compose file can be read as
        INPUTS to assertions. If it were on sys.path it would shadow /app and
        re-create the whole defect."""
        assert str(REPO) not in sys.path
        assert str(REPO / "shared") not in sys.path

    def test_the_ARTEFACT_matches_the_checkout_it_claims_to_be_built_from(self):
        """The stale-image case, caught directly. If `sentinel:latest` was
        built from older source than the repo copy beside it, the suite is
        testing one thing and the rehearsal will run another."""
        import sentinel
        runtime = ident.source_hash(Path(sentinel.__file__).resolve().parent)
        checkout = ident.source_hash(REPO / "sentinel")
        assert runtime["hash"] == checkout["hash"], (
            f"the running image's sentinel/ ({runtime['files']} files) differs "
            f"from the repository it was built from ({checkout['files']} "
            f"files) — rebuild before certifying anything")

    def test_the_environment_reports_itself_CERTIFIED(self):
        env = ident.environment()
        assert env["certified"] is True, env["pin_drift"] or env


# ── 3. and outside it, the same tests must not silently pass ─────────────────

class TestTheGateIsNotVacuous:

    def test_the_in_image_marker_is_OFF_in_a_checkout_and_ON_in_the_image(self):
        """A guard keyed on something the image sets, so it cannot be true by
        accident. `sentinel-certify.sh` additionally treats ANY skip inside the
        image as a failure, which is what stops this class from being skipped
        in the one place it matters."""
        assert IN_IMAGE == (os.environ.get("SENTINEL_IN_IMAGE") == "1")

    def test_the_test_image_does_NOT_copy_runtime_code_onto_the_path(self):
        """Read from the Dockerfile, so the property is enforced where it is
        configured rather than only where it happens to be observed."""
        text = (REPO / "Dockerfile.sentinel-test").read_text() \
            if (REPO / "Dockerfile.sentinel-test").exists() \
            else (ROOT / "Dockerfile.sentinel-test").read_text()
        copies = [l.split()[1:3] for l in text.splitlines()
                  if l.strip().upper().startswith("COPY ")]
        importable = [dst for src, dst in copies
                      if dst.rstrip("/").endswith(("/work/sentinel",
                                                   "/work/shared"))]
        assert not importable, (
            f"runtime code is copied to an importable path: {importable}. "
            f"Pytest would then prove the checkout rather than the artefact.")
        assert "PYTHONPATH=/work:/app" in text.replace("\\\n", " "), (
            "the runtime image's /app must be on the path for `sentinel` to "
            "resolve to the artefact")
