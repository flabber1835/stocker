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
python 3.12.13               sentinel-authorized:latest sha256:...
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

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

try:
    from scripts.sentinel_certification_state import validate_closure_context
except ModuleNotFoundError as exc:
    if exc.name not in {"scripts", "scripts.sentinel_certification_state"}:
        raise
    try:
        from sentinel_certification_state import validate_closure_context
    except ModuleNotFoundError as direct_exc:
        if direct_exc.name != "sentinel_certification_state":
            raise
        # Some certification tests load this file directly from its path while
        # deliberately keeping the inspection checkout off ``sys.path``. Load
        # the sibling without weakening that runtime/inspection boundary.
        sibling = Path(__file__).with_name("sentinel_certification_state.py")
        spec = importlib.util.spec_from_file_location(
            "sentinel_certification_state_sibling", sibling
        )
        if spec is None or spec.loader is None:  # pragma: no cover
            raise ImportError("cannot load " + str(sibling))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        validate_closure_context = module.validate_closure_context


_IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache"}
_IGNORED_SUFFIXES = {".pyc", ".pyo"}
COMPLETION_FIELDS = (
    "book_artifact_sha256",
    "rejection_audit_sha256",
    "rehearsal_hashes",
    "rehearsal_run_id",
    "rehearsal_spec",
    "rehearsal_equivalence",
    "settlement_counters",
    "terminal_reconciliation",
    "bt_engine_identity",
    "final_identity_hash",
    "final_corpus_hash",
)


def _clear_completion(manifest: dict) -> None:
    for key in COMPLETION_FIELDS:
        manifest[key] = None


def begin_finalization(manifest: dict) -> dict:
    """Enter FINALIZING without allowing completed-looking partial evidence."""
    if manifest.get("lifecycle") == "FINALIZED":
        raise ValueError("manifest is already FINALIZED")
    if manifest.get("lifecycle") not in {
            "READY_FOR_REHEARSAL", "BLOCKED", "FINALIZING"}:
        raise ValueError(
            f"manifest lifecycle is {manifest.get('lifecycle')!r}, not "
            "READY_FOR_REHEARSAL")
    _clear_completion(manifest)
    manifest["lifecycle"] = "FINALIZING"
    manifest["verdict"] = None
    manifest["failures"] = []
    # Preserve the preceding attempt as diagnostics until this fresh attempt
    # reaches its own durable result. In particular, a crash after this write
    # leaves FINALIZING resumable rather than requiring a manual repair.
    return manifest


def block_finalization(
        manifest: dict, reasons, *, attempt: dict | None = None) -> dict:
    """Persist a blocked outcome while retaining all attempted evidence."""
    if manifest.get("lifecycle") == "FINALIZED":
        return manifest
    _clear_completion(manifest)
    failures = list(manifest.get("failures") or [])
    for reason in reasons:
        if reason not in failures:
            failures.append(reason)
    saved_attempt = dict(attempt if attempt is not None else
                         (manifest.get("last_finalization_attempt") or {}))
    attempt_failures = list(saved_attempt.get("failures") or [])
    for reason in failures:
        if reason not in attempt_failures:
            attempt_failures.append(reason)
    saved_attempt["failures"] = attempt_failures
    manifest["last_finalization_attempt"] = saved_attempt
    manifest["lifecycle"] = "BLOCKED"
    manifest["verdict"] = "BLOCKED"
    manifest["failures"] = failures
    return manifest


def finish_finalization(manifest: dict, attempt: dict, failures) -> dict:
    """Publish completion fields iff every finalization gate passed."""
    saved_attempt = dict(attempt)
    failures = list(failures)
    for key in COMPLETION_FIELDS:
        if not saved_attempt.get(key):
            failures.append(f"attempted {key} is null")
    saved_attempt["failures"] = failures
    manifest["last_finalization_attempt"] = saved_attempt
    if failures:
        return block_finalization(
            manifest, failures, attempt=saved_attempt)
    for key in COMPLETION_FIELDS:
        manifest[key] = saved_attempt.get(key)
    manifest["lifecycle"] = "FINALIZED"
    manifest["verdict"] = "PASS"
    manifest["failures"] = []
    return manifest


def finalization_provenance_failures(
        manifest: dict, final_identity: dict, summary: dict
) -> tuple[dict, list[str]]:
    """Return exact generation/source/identity drift failures for a run."""
    failures: list[str] = []
    generations = manifest.get("parity_generations") or {}
    provenance = summary.get("provenance") or {}
    for key in ("sentinel_data_version", "canonical_data_version",
                "canonical_source_mode"):
        if generations.get(key) in (None, ""):
            failures.append(f"parity_generations.{key} is MISSING")
    expected_generation = generations.get("canonical_data_version")
    actual_generation = provenance.get("bt_data_version")
    if str(actual_generation) != str(expected_generation):
        failures.append(
            "run provenance bt_data_version is "
            f"{actual_generation!r}, not frozen canonical generation "
            f"{expected_generation!r}")
    expected_mode = generations.get("canonical_source_mode")
    actual_mode = provenance.get("bt_data_source_mode")
    if str(actual_mode) != str(expected_mode):
        failures.append(
            "run provenance bt_data_source_mode is "
            f"{actual_mode!r}, not frozen source mode {expected_mode!r}")
    if provenance.get("bt_data_status") != "READY":
        failures.append(
            "run provenance bt_data_status is "
            f"{provenance.get('bt_data_status')!r}, not 'READY'")

    final_corpus = final_identity.get("corpus") or {}
    if final_identity.get("identity_hash") != manifest.get("identity_hash"):
        failures.append(
            "the final Sentinel runtime identity differs from the frozen "
            "identity")
    if str(final_corpus.get("data_version")) != str(
            generations.get("sentinel_data_version")):
        failures.append(
            "the final Sentinel data_version is "
            f"{final_corpus.get('data_version')!r}, not parity publication "
            f"{generations.get('sentinel_data_version')!r}")
    if final_corpus.get("corpus_hash") != manifest.get("corpus_hash"):
        failures.append(
            "the final Sentinel corpus_hash differs from the corpus parity "
            "certified")
    return provenance, failures


def bundle_source_hash(spec, *, python_only: bool = False) -> str | None:
    """Hash files under ``(source, logical_prefix)`` mappings.

    Logical paths make an assembled image tree comparable with the source files
    that Docker copied into it even though their absolute paths differ. Later
    mappings replace an earlier logical path, matching Docker COPY overlay
    semantics (notably bt-engine's ``app/live`` adapters).
    """
    files: dict[str, Path] = {}
    for source, logical_prefix in spec:
        source = Path(source)
        if not source.exists():
            return None
        candidates = [source] if source.is_file() else sorted(source.rglob("*"))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = (Path(candidate.name) if source.is_file()
                        else candidate.relative_to(source))
            if any(part in _IGNORED_PARTS for part in relative.parts):
                continue
            if candidate.suffix in _IGNORED_SUFFIXES:
                continue
            if python_only and candidate.suffix != ".py":
                continue
            logical = (Path(logical_prefix) / relative).as_posix()
            files[logical] = candidate
    if not files:
        return None
    digest = hashlib.sha256()
    for logical, path in sorted(files.items()):
        digest.update(logical.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode())
        digest.update(b"\n")
    return digest.hexdigest()


_IMAGE_BUNDLE_PROGRAM = r"""
import hashlib, json
from pathlib import Path
spec, python_only = json.loads(__import__('sys').argv[1]), __import__('sys').argv[2] == '1'
files = {}
for source_text, logical_prefix in spec:
    source = Path(source_text)
    if not source.exists():
        raise SystemExit(3)
    candidates = [source] if source.is_file() else sorted(source.rglob('*'))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        relative = Path(candidate.name) if source.is_file() else candidate.relative_to(source)
        if any(part in {'.git', '__pycache__', '.pytest_cache'} for part in relative.parts):
            continue
        if candidate.suffix in {'.pyc', '.pyo'} or (python_only and candidate.suffix != '.py'):
            continue
        files[(Path(logical_prefix) / relative).as_posix()] = candidate
if not files:
    raise SystemExit(4)
digest = hashlib.sha256()
for logical, path in sorted(files.items()):
    digest.update(logical.encode()); digest.update(b'\0')
    digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode()); digest.update(b'\n')
print(digest.hexdigest())
"""


def image_bundle_source_hash(ref: str, spec, *, python_only: bool = False) -> str | None:
    out = sh("docker", "run", "--rm", "--entrypoint", "python", ref, "-c",
             _IMAGE_BUNDLE_PROGRAM, json.dumps(spec), "1" if python_only else "0")
    return out or None


def _assembled_bt_engine_spec(root: Path):
    return [
        (root / "services" / "bt-engine" / "app", ""),
        (root / "services" / "backtester" / "app" / "wealth_core_replay.py",
         "live"),
        (root / "services" / "backtester" / "app" / "wealth_core_benchmark.py",
         "live"),
    ]


def _certification_input_spec(root: Path, *, image: bool = False):
    """The source/read-only inputs copied into ``sentinel-test``.

    Keep this list aligned with Dockerfile.sentinel-test. Missing inputs fail the
    digest instead of silently shrinking its scope.
    """
    if image:
        work, repo = Path("/work"), Path("/work/repo")
    else:
        work = repo = root
    return [
        (work / "tests", "tests"),
        (work / "services" / "backtester", "services/backtester"),
        (work / "tools", "tools"),
        (work / "docs" / "sentinel-handoff" / "00_README",
         "docs/sentinel-handoff/00_README"),
        (work / "docs" / "sentinel-handoff" /
         "02_SENTINEL_1P1_FROZEN_ORACLE",
         "docs/sentinel-handoff/02_SENTINEL_1P1_FROZEN_ORACLE"),
        (work / "docs" / "sentinel-handoff" / "04_BREADTH_ORACLES",
         "docs/sentinel-handoff/04_BREADTH_ORACLES"),
        (work / "docs" / "sentinel-breadth-reconstruction",
         "docs/sentinel-breadth-reconstruction"),
        (work / "docs" / "sentinel-reference-implementation",
         "docs/sentinel-reference-implementation"),
        (repo / "scripts", "scripts"),
        (repo / "sentinel", "sentinel"),
        (repo / "shared", "shared"),
        (repo / "services" / "bt-engine", "services/bt-engine"),
        (repo / "services" / "bt-data", "services/bt-data"),
        (repo / "Dockerfile.base", ""),
        (repo / "Dockerfile.sentinel", ""),
        (repo / "Dockerfile.sentinel-authorized", ""),
        (repo / "Dockerfile.sentinel-test", ""),
        (repo / "deploy" / "sentinel-authorized-runtime-v1", "deploy"),
        (repo / "docker-compose.sentinel.yml", ""),
        (repo / "docker-compose.sentinel-automation.yml", ""),
        (repo / "docker-compose.backtest.yml", ""),
        (repo / "docker-compose.sentinel-backup.yml", ""),
        (repo / ".dockerignore", ""),
        (repo / ".gitattributes", ""),
        (repo / ".github" / "workflows" / "sentinel-safety.yml", ""),
        (repo / ".env.example", ""),
        (repo / "Makefile", ""),
        (repo / "README.md", ""),
        (repo / "docs" / "main-review-remediation.md", "docs"),
        (repo / "docs" / "sentinel-deployment.md", "docs"),
        (repo / "docs" / "sentinel-paper-activation.md", "docs"),
        (repo / "docs" / "sentinel-stage-4-automation.md", "docs"),
    ]


def checkout_source_hashes(root: Path) -> dict[str, str | None]:
    return {
        "sentinel": bundle_source_hash(
            [(root / "sentinel", "")], python_only=True),
        "wealth_core": bundle_source_hash(
            [(root / "shared" / "stock_strategy_shared" / "wealth_core",
              "")], python_only=True),
        "bt_data": bundle_source_hash([
            (root / "services" / "bt-data" / "app", "app"),
            (root / "services" / "bt-data" / "sql", "sql"),
        ]),
        "bt_engine_app": bundle_source_hash(
            _assembled_bt_engine_spec(root), python_only=True),
        "certification_inputs": bundle_source_hash(
            _certification_input_spec(root)),
    }


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
            "source_revision": sh(
                "docker", "image", "inspect", ref, "--format",
                '{{ index .Config.Labels "org.opencontainers.image.revision" }}'),
            "repo_digests": digests}


def bt_engine_app_source_hash(ref: str) -> str | None:
    """The bt-engine LOADER source, read OUT OF THE BUILT IMAGE.

    Recorded at FREEZE time so the manifest names the loader before any
    rehearsal exists. Without it `bt_engine_app_source_hash` was
    required-present and compared against nothing — a change to the code that
    READS THE CORPUS could land after the manifest was written and the Wealth
    Core hash would still match, because Wealth Core had not moved.

    READ FROM THE IMAGE, NOT FROM THE CHECKOUT, and that distinction is not
    stylistic. `services/bt-engine/Dockerfile` assembles `/app/app` from the
    certification app plus the surviving backtester corpus adapters:

    ```text
    services/bt-engine/app/                     -> /app/app/
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


def bt_engine_runtime_identity(ref: str) -> dict | None:
    """Read the dependency identity from the exact built bt-engine image."""
    out = sh(
        "docker", "run", "--rm", "--entrypoint", "python", ref, "-c",
        "import json;"
        "from stock_strategy_shared.runtime_identity import dependency_identity;"
        "print(json.dumps(dependency_identity('/app/requirements.lock'),"
        "sort_keys=True,separators=(',',':')))"
    )
    try:
        value = json.loads(out) if out else None
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def build(art: Path, stamp: str, lock_sha: str,
          postgres_ref: str = "postgres:16",
          bt_engine_ref: str = "stocker-bt-engine:latest",
          bt_data_ref: str = "stocker-bt-bt-data:latest",
          runtime_ref: str = "sentinel-authorized:latest",
          test_ref: str = "sentinel-test:latest",
          certified_baseline: Path | None = None,
          closure_transition: Path | None = None,
          enforce_closure_context: bool = False) -> dict:
    rec = json.loads((art / "identity-env.json").read_text())
    env = rec["environment"]
    git_commit = sh("git", "rev-parse", "HEAD")
    closure_context = {"baseline": None, "transition": None}
    if enforce_closure_context:
        closure_context = validate_closure_context(
            art=art, identity_path=art / "identity-env.json",
            lock_path=Path("sentinel/requirements.lock"),
            git_commit=git_commit or "", baseline_path=certified_baseline,
            transition_path=closure_transition,
        )
    checkout_hashes = checkout_source_hashes(Path.cwd())
    engine_hash = bt_engine_app_source_hash(bt_engine_ref)
    engine_runtime = bt_engine_runtime_identity(bt_engine_ref)
    image_hashes = {
        "sentinel": env["sentinel_source"]["hash"],
        "wealth_core": env["wealth_core_source"]["hash"],
        "bt_data": image_bundle_source_hash(bt_data_ref, [
            ["/app/app", "app"], ["/app/sql", "sql"],
        ]),
        "bt_engine_app": engine_hash,
        "certification_inputs": image_bundle_source_hash(
            test_ref,
            [[str(source), logical] for source, logical in
             _certification_input_spec(Path("/work/repo"), image=True)]),
    }
    manifest = {
        "schema": "sentinel.certification_manifest/2",
        "lifecycle": "FROZEN",
        "verdict": None,
        "failures": [],
        "git_commit": git_commit,
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
        "sentinel_runtime_image": image(runtime_ref),
        "sentinel_test_image": image(test_ref),
        # THE PINNED, DIGEST-QUALIFIED REFERENCE from compose — not the bare
        # `postgres:16` tag. PostgreSQL PRODUCES the corpus being certified, so
        # a record naming whatever happens to be tagged `postgres:16` locally
        # could name an entirely unrelated server. On a clean machine the bare
        # tag simply resolved to nothing and certification continued.
        "postgres_image": image(postgres_ref),
        # The service that normalises vendor rows into the corpus. A corpus
        # digest names its output, not the code and dependencies that decided
        # how source fields were interpreted.
        "bt_data_image": image(bt_data_ref),
        # THE ENGINE THAT WILL RUN THE REHEARSAL, named BEFORE it runs one.
        # Comparing the run only against whatever the bt-engine tag points at
        # during finalization accepts any correctly self-identifying artefact
        # that happens to run afterwards — including one built from loader
        # source that changed after this manifest was frozen.
        "bt_engine_image": image(bt_engine_ref),
        "bt_engine_app_source_hash": engine_hash,
        "bt_engine_runtime_identity": engine_runtime,
        "checkout_source_hashes": checkout_hashes,
        "image_source_hashes": image_hashes,
        "identity_hash": rec["identity_hash"],
        "distributions_hash": env["distributions_hash"],
        "distributions_count": env["distributions_count"],
        "requirements_lock_sha256": lock_sha,
        "previous_certified_evidence": closure_context["baseline"],
        "closure_transition": closure_context["transition"],
        "sentinel_source_hash": env["sentinel_source"]["hash"],
        "wealth_core_source_hash": env["wealth_core_source"]["hash"],
        "python": env["python"],
        "calendar_version": env["calendar_version"],
        # Filled in by later steps and by the rehearsal itself.
        "corpus_hash": None,
        "parity_generations": None,
        "preseed_rejection_audit_sha256": None,
        "book_artifact_sha256": None,
        "rejection_audit_sha256": None,
        "rehearsal_hashes": None,
        "rehearsal_run_id": None,
        "rehearsal_spec": None,
        "rehearsal_equivalence": None,
        "settlement_counters": None,
        "terminal_reconciliation": None,
        "bt_engine_identity": None,
        "final_identity_hash": None,
        "final_corpus_hash": None,
        "last_finalization_attempt": None,
    }
    return manifest


#: Every image the record NAMES. All three participate in producing or
#: verifying the evidence, so an unnamed one is a hole in the record rather
#: than a missing convenience field.
REQUIRED_IMAGES = ("sentinel_runtime_image", "sentinel_test_image",
                   "postgres_image", "bt_data_image", "bt_engine_image")
SOURCE_IMAGES = ("sentinel_runtime_image", "sentinel_test_image",
                 "bt_data_image", "bt_engine_image")


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("art")
    ap.add_argument("stamp")
    ap.add_argument("lock_sha")
    ap.add_argument("--postgres-ref", default="postgres:16")
    ap.add_argument("--bt-engine-ref", default="stocker-bt-engine:latest")
    ap.add_argument("--bt-data-ref", default="stocker-bt-bt-data:latest")
    ap.add_argument("--runtime-ref", default="sentinel-authorized:latest")
    ap.add_argument("--test-ref", default="sentinel-test:latest")
    ap.add_argument("--certified-baseline", type=Path)
    ap.add_argument("--closure-transition", type=Path)
    ap.add_argument("--enforce-closure-context", action="store_true")
    ap.add_argument("--require-images", action="store_true",
                    help="exit non-zero unless every named image resolved and "
                         "the source tree is clean. Used before the "
                         "irreversible step, where a warning is not enough.")
    args = ap.parse_args(list(argv or sys.argv[1:]))
    art, stamp, lock_sha = Path(args.art), args.stamp, args.lock_sha
    m = build(art, stamp, lock_sha, postgres_ref=args.postgres_ref,
              bt_engine_ref=args.bt_engine_ref, bt_data_ref=args.bt_data_ref,
              runtime_ref=args.runtime_ref, test_ref=args.test_ref,
              certified_baseline=args.certified_baseline,
              closure_transition=args.closure_transition,
              enforce_closure_context=args.enforce_closure_context)

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
    for key in SOURCE_IMAGES:
        revision = m[key].get("source_revision")
        if not revision or revision == "unknown":
            problems.append(
                f"{key} has no immutable source revision label")
        elif revision != m["git_commit"]:
            problems.append(
                f"{key} was built from {revision}, not current "
                f"git_commit {m['git_commit']}")
    engine_runtime = m.get("bt_engine_runtime_identity")
    if (not isinstance(engine_runtime, dict)
            or set(engine_runtime) != {
                "requirements_lock_sha256", "distributions_sha256",
                "distributions_count"}
            or any(not isinstance(engine_runtime.get(field), str)
                   or len(engine_runtime[field]) != 64
                   for field in (
                       "requirements_lock_sha256", "distributions_sha256"))
            or type(engine_runtime.get("distributions_count")) is not int
            or engine_runtime["distributions_count"] < 1):
        problems.append(
            "bt_engine_runtime_identity could not be read from the built "
            "engine; its exact dependency closure is unknown")
    checkout_hashes = m["checkout_source_hashes"]
    image_hashes = m["image_source_hashes"]
    for key in sorted(checkout_hashes):
        checkout_hash, image_hash = checkout_hashes[key], image_hashes.get(key)
        if not checkout_hash:
            problems.append(
                f"checkout source hash {key} could not be computed; the "
                "certification input set is incomplete")
        if not image_hash:
            problems.append(
                f"image source hash {key} could not be read; the built bytes "
                "cannot be compared with the checkout")
        elif checkout_hash and checkout_hash != image_hash:
            problems.append(
                f"{key} source differs between the clean checkout "
                f"({checkout_hash}) and built image ({image_hash}); an image "
                "label naming the same commit is not proof of a clean build")
    for p in problems:
        print(f"  {'REFUSED' if args.require_images else 'WARNING'}: {p}")

    out = art / f"manifest-{stamp}.json"
    rendered = json.dumps(m, indent=2, sort_keys=True).encode("utf-8")
    output_conflict = False
    if out.exists() and out.read_bytes() != rendered:
        # A finalized or abandoned lifecycle record is evidence. A new freeze
        # for the same window must never erase it merely because the historical
        # filename is shared. Retain the refused attempt separately so the
        # operator can diagnose it without clobbering the existing record.
        suffix = hashlib.sha256(rendered).hexdigest()[:16]
        refused = art / f"manifest-refused-{stamp}-{suffix}.json"
        try:
            with refused.open("xb") as handle:
                handle.write(rendered)
        except FileExistsError:
            if refused.read_bytes() != rendered:
                raise
        print(f"  REFUSED: {out} already contains different evidence")
        print(f"  retained attempted bytes at {refused}")
        output_conflict = True
    elif not out.exists():
        with out.open("xb") as handle:
            handle.write(rendered)
    print(f"  git      {m['git_commit']} clean={m['git_tree_clean']}")
    print(f"  runtime  {m['sentinel_runtime_image']['id']}")
    print(f"  test     {m['sentinel_test_image']['id']}")
    for key, digest in sorted(m["image_source_hashes"].items()):
        print(f"  source   {key:22} {digest}")
    print(f"  closure  {m['distributions_hash'][:16]}  "
          f"lock {m['requirements_lock_sha256'][:16]}")
    print(f"  -> {out}")
    # WRITTEN EVEN WHEN REFUSING, so the operator can see exactly which field
    # was missing rather than being told a file could not be produced.
    return 1 if output_conflict or (problems and args.require_images) else 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
