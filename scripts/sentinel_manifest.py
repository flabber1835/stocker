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


def bt_engine_app_source_hash(ref: str) -> str | None:
    """The bt-engine LOADER source, read OUT OF THE BUILT IMAGE.

    Recorded at FREEZE time so the manifest names the loader before any
    rehearsal exists. Without it `bt_engine_app_source_hash` was
    required-present and compared against nothing — a change to the code that
    READS THE CORPUS could land after the manifest was written and the Wealth
    Core hash would still match, because Wealth Core had not moved.

    READ FROM THE IMAGE, NOT FROM THE CHECKOUT, and that distinction is not
    stylistic. `services/bt-engine/Dockerfile` assembles `/app/app` from FOUR
    source trees:

    ```text
    services/bt-engine/app/                     -> /app/app/
    services/pipeline/app/{factors,rank}.py     -> /app/app/live/
    services/portfolio-builder/app/select.py    -> /app/app/live/
    services/backtester/app/wealth_core_*.py    -> /app/app/live/
    ```

    So a digest of `services/bt-engine/app` alone is a DIFFERENT tree from the
    one the run hashes, and the comparison would have failed on every single
    run — a gate that always fires is as useless as one that never does, and
    far more likely to be disabled. Hashing the image asks the artefact itself,
    which is what is being certified anyway.
    """
    out = sh("docker", "run", "--rm", "--entrypoint", "python", ref, "-c",
             "from stock_strategy_shared import identity_hashes as i;"
             "print(i.package_source_hash('/app/app'))")
    return out or None


def build(art: Path, stamp: str, lock_sha: str,
          postgres_ref: str = "postgres:16",
          bt_engine_ref: str = "stocker-bt-engine:latest") -> dict:
    rec = json.loads((art / "identity-env.json").read_text())
    env = rec["environment"]
    manifest = {
        "schema": "sentinel.certification_manifest/1",
        "git_commit": sh("git", "rev-parse", "HEAD"),
        # A DIRTY tree means the manifest names a commit that is not what was
        # built. Recorded as a field so the verdict is the reader's, and warned
        # about loudly because it invalidates the git_commit line above it.
        "git_tree_clean": sh("git", "status", "--porcelain") == "",
        # AND WHICH PATHS. The refusal used to say only that the tree was
        # dirty, which stops the run without saying what to look at — the
        # operator then hunts through a repo they have not edited. Capped
        # because the field is a diagnostic, not an inventory.
        "git_dirty_paths": [l for l in
                            (sh("git", "status", "--porcelain") or "").splitlines()
                            if l.strip()][:50],
        "sentinel_runtime_image": image("sentinel:latest"),
        "sentinel_test_image": image("sentinel-test:latest"),
        # THE PINNED, DIGEST-QUALIFIED REFERENCE from compose — not the bare
        # `postgres:16` tag. PostgreSQL PRODUCES the corpus being certified, so
        # a record naming whatever happens to be tagged `postgres:16` locally
        # could name an entirely unrelated server. On a clean machine the bare
        # tag simply resolved to nothing and certification continued.
        "postgres_image": image(postgres_ref),
        # THE ENGINE THAT WILL RUN THE REHEARSAL, named BEFORE it runs one.
        # Comparing the run only against whatever the bt-engine tag points at
        # during finalization accepts any correctly self-identifying artefact
        # that happens to run afterwards — including one built from loader
        # source that changed after this manifest was frozen.
        "bt_engine_image": image(bt_engine_ref),
        "bt_engine_app_source_hash": bt_engine_app_source_hash(bt_engine_ref),
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
                   "postgres_image", "bt_engine_image")


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("art")
    ap.add_argument("stamp")
    ap.add_argument("lock_sha")
    ap.add_argument("--postgres-ref", default="postgres:16")
    ap.add_argument("--bt-engine-ref", default="stocker-bt-engine:latest")
    ap.add_argument("--require-images", action="store_true",
                    help="exit non-zero unless every named image resolved and "
                         "the source tree is clean. Used before the "
                         "irreversible step, where a warning is not enough.")
    args = ap.parse_args(list(argv or sys.argv[1:]))
    art, stamp, lock_sha = Path(args.art), args.stamp, args.lock_sha
    m = build(art, stamp, lock_sha, postgres_ref=args.postgres_ref,
              bt_engine_ref=args.bt_engine_ref)

    problems = []
    if not m["git_tree_clean"]:
        listing = "\n".join(f"      {p}" for p in m["git_dirty_paths"])
        problems.append("the working tree is DIRTY, so git_commit names a "
                        f"commit that is not what was built:\n{listing}\n"
                        "    (` M` = modified, `??` = untracked. If every entry "
                        "shows only a MODE change, this filesystem is rewriting "
                        "permission bits and `git config core.fileMode false` "
                        "is the fix — check with `git diff`.)")
    for key in REQUIRED_IMAGES:
        if not m[key]["id"]:
            problems.append(f"{key} ({m[key]['ref']}) could not be inspected — "
                            f"the record cannot name it")
    if not m["bt_engine_app_source_hash"]:
        problems.append("bt_engine_app_source_hash could not be read out of "
                        f"{args.bt_engine_ref} — the loader that reads the "
                        "corpus would be unnamed")
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
