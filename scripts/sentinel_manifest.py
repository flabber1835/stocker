"""The identity of the ARTEFACT, assembled on the HOST.

`sentinel identity` describes the environment INSIDE the container — the
interpreter, the resolved package closure, the source trees it imported. It
cannot describe the image, and that is not an oversight to fix in the container:
a process has no reliable way to discover the id of the image it is running in.
Docker knows; the container does not.

And the image is the thing actually being certified. Everything else — the base
digest, the Postgres digest, the source hashes, the closure — describes INPUTS
to a build. A rehearsal is run by one specific built image, and until that image
is named, the record describes a recipe rather than the artefact.

```text
inputs, from inside          the artefact, from outside
--------------------         --------------------------
python 3.12.13               sentinel:latest      sha256:...
base image digest            sentinel-test:latest sha256:...
package closure              postgres:16          sha256:...
sentinel/wealth core source  the git commit they were built from
```

## Image ID and repo digest are different things, and both are recorded

`.Id` is the local content id of the image as built. `RepoDigests` is the
immutable registry digest, and it is EMPTY until the image is pushed. It is
recorded as a field rather than omitted, because deploying to another machine
must eventually go by that digest: rebuilding elsewhere from the same Dockerfile
and calling the result equivalent is precisely the assumption the pins, the lock
and this manifest exist to remove.

## The null fields are deliberate

`corpus_hash`, the book artifact, the rejection audit and the rehearsal hashes
are filled in by later steps. They are present as `null` so an incomplete
manifest is visibly incomplete, rather than a differently shaped object that a
reader has to notice is missing something.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def sh(*cmd) -> str | None:
    """Run a command, returning None rather than raising.

    A missing image is a FACT to record — the manifest says `null` and the
    reader sees it — not a reason to abandon the record. An exception here
    would lose the fields that did resolve.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:                                        # noqa: BLE001
        return None


def image(ref: str) -> dict:
    digests = sh("docker", "image", "inspect", ref, "--format",
                 "{{json .RepoDigests}}")
    try:
        digests = json.loads(digests) if digests else []
    except Exception:                                        # noqa: BLE001
        digests = []
    return {"ref": ref,
            "id": sh("docker", "image", "inspect", ref, "--format", "{{.Id}}"),
            "repo_digests": digests}


def build(art: Path, stamp: str, lock_sha: str,
          postgres_ref: str = "postgres:16") -> dict:
    rec = json.loads((art / "identity-env.json").read_text())
    env = rec["environment"]
    manifest = {
        "schema": "sentinel.certification_manifest/1",
        "git_commit": sh("git", "rev-parse", "HEAD"),
        # A DIRTY tree means the manifest names a commit that is not what was
        # built. Recorded as a field so the verdict is the reader's, and warned
        # about loudly because it invalidates the git_commit line above it.
        "git_tree_clean": sh("git", "status", "--porcelain") == "",
        "sentinel_runtime_image": image("sentinel:latest"),
        "sentinel_test_image": image("sentinel-test:latest"),
        # THE PINNED, DIGEST-QUALIFIED REFERENCE from compose — not the bare
        # `postgres:16` tag. PostgreSQL PRODUCES the corpus being certified, so
        # a record naming whatever happens to be tagged `postgres:16` locally
        # could name an entirely unrelated server. On a clean machine the bare
        # tag simply resolved to nothing and certification continued.
        "postgres_image": image(postgres_ref),
        "identity_hash": rec["identity_hash"],
        "distributions_hash": env["distributions_hash"],
        "distributions_count": env["distributions_count"],
        "requirements_lock_sha256": lock_sha,
        "sentinel_source_hash": env["sentinel_source"]["hash"],
        "wealth_core_source_hash": env["wealth_core_source"]["hash"],
        "python": env["python"],
        "calendar_version": env["calendar_version"],
        # Filled in by later steps and by the rehearsal itself.
        "corpus_hash": None,
        "book_artifact_sha256": None,
        "rejection_audit_sha256": None,
        "rehearsal_hashes": None,
    }
    return manifest


#: Every image the record NAMES. All three participate in producing or
#: verifying the evidence, so an unnamed one is a hole in the record rather
#: than a missing convenience field.
REQUIRED_IMAGES = ("sentinel_runtime_image", "sentinel_test_image",
                   "postgres_image")


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("art")
    ap.add_argument("stamp")
    ap.add_argument("lock_sha")
    ap.add_argument("--postgres-ref", default="postgres:16")
    ap.add_argument("--require-images", action="store_true",
                    help="exit non-zero unless every named image resolved and "
                         "the source tree is clean. Used before the "
                         "irreversible step, where a warning is not enough.")
    args = ap.parse_args(list(argv or sys.argv[1:]))
    art, stamp, lock_sha = Path(args.art), args.stamp, args.lock_sha
    m = build(art, stamp, lock_sha, postgres_ref=args.postgres_ref)

    problems = []
    if not m["git_tree_clean"]:
        problems.append("the working tree is DIRTY, so git_commit names a "
                        "commit that is not what was built")
    for key in REQUIRED_IMAGES:
        if not m[key]["id"]:
            problems.append(f"{key} ({m[key]['ref']}) could not be inspected — "
                            f"the record cannot name it")
    for p in problems:
        print(f"  {'REFUSED' if args.require_images else 'WARNING'}: {p}")

    out = art / f"manifest-{stamp}.json"
    out.write_text(json.dumps(m, indent=2, sort_keys=True))
    print(f"  git      {m['git_commit']} clean={m['git_tree_clean']}")
    print(f"  runtime  {m['sentinel_runtime_image']['id']}")
    print(f"  test     {m['sentinel_test_image']['id']}")
    print(f"  closure  {m['distributions_hash'][:16]}  "
          f"lock {m['requirements_lock_sha256'][:16]}")
    print(f"  -> {out}")
    # WRITTEN EVEN WHEN REFUSING, so the operator can see exactly which field
    # was missing rather than being told a file could not be produced.
    return 1 if (problems and args.require_images) else 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
