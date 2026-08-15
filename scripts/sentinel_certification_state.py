"""Immutable host-side state for certification image and closure phases."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence


BUILD_SCHEMA = "sentinel.certification-image-build/1"
PROMOTION_SCHEMA = "sentinel.certification-image-promotion/1"
TRANSITION_SCHEMA = "sentinel.certification-closure-transition/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class CertificationStateRefused(ValueError):
    """The supplied state cannot authorize the requested phase."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: object, *, label: str, git: bool = False) -> str:
    pattern = _GIT_SHA if git else _SHA256
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise CertificationStateRefused(label + " is not a canonical digest")
    return value


def _mapping(value: object, *, label: str,
             fields: object = None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CertificationStateRefused(label + " is not an object")
    if fields is not None and set(value) != set(fields):
        raise CertificationStateRefused(label + " fields are not the exact schema")
    return value


def _json_object(raw: bytes, *, label: str) -> Mapping[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CertificationStateRefused(
                    label + " contains duplicate key " + repr(key)
                )
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CertificationStateRefused(label + " is not valid UTF-8 JSON") from exc
    return _mapping(value, label=label)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_no_clobber(value: Mapping[str, Any], output: Path) -> None:
    """Atomically publish canonical bytes; an identical retry is idempotent."""
    output = Path(output)
    raw = canonical_bytes(value) + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() == raw:
            return
        raise CertificationStateRefused(str(output) + " already exists")
    fd, name = tempfile.mkstemp(
        dir=str(output.parent), prefix="." + output.name + ".", suffix=".tmp"
    )
    temporary = Path(name)
    linked = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(str(temporary), str(output))
        linked = True
        _fsync_directory(output.parent)
    except BaseException:
        if linked:
            try:
                output.unlink()
            except OSError:
                pass
        raise
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    _fsync_directory(output.parent)


def _docker_inspect(ref: str, *, invoke: Callable[..., Any] = subprocess.run
                    ) -> Mapping[str, Any]:
    try:
        completed = invoke(
            ["docker", "image", "inspect", ref],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except OSError as exc:
        raise CertificationStateRefused("Docker could not inspect " + ref) from exc
    if completed.returncode != 0:
        raise CertificationStateRefused("Docker could not inspect " + ref)
    try:
        decoded = json.loads(bytes(completed.stdout))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CertificationStateRefused("Docker inspect was not JSON") from exc
    if not isinstance(decoded, list) or len(decoded) != 1:
        raise CertificationStateRefused("Docker inspect did not name one image")
    value = _mapping(decoded[0], label="Docker image identity")
    image_id = value.get("Id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise CertificationStateRefused("Docker image id is malformed")
    labels = (value.get("Config") or {}).get("Labels") or {}
    if not isinstance(labels, dict):
        raise CertificationStateRefused("Docker image labels are malformed")
    revision = labels.get("org.opencontainers.image.revision")
    repo_digests = value.get("RepoDigests") or []
    if not isinstance(repo_digests, list):
        raise CertificationStateRefused("Docker RepoDigests are malformed")
    return {
        "ref": ref,
        "id": image_id,
        "source_revision": revision,
        "repo_digests": list(repo_digests),
    }


def _repository(tag: str) -> str:
    slash = tag.rfind("/")
    colon = tag.rfind(":")
    repository = tag[:colon] if colon > slash else tag
    if not repository or "@" in repository:
        raise CertificationStateRefused("promotion tag is malformed")
    return repository


def _promoted_identity(tag: str, *, invoke=subprocess.run) -> Mapping[str, Any]:
    identity = dict(_docker_inspect(tag, invoke=invoke))
    prefix = _repository(tag) + "@sha256:"
    matching = sorted({ref for ref in identity["repo_digests"]
                       if isinstance(ref, str) and ref.startswith(prefix)})
    if len(matching) != 1:
        raise CertificationStateRefused(
            tag + " does not have exactly one matching immutable RepoDigest"
        )
    payload = matching[0].rsplit("@sha256:", 1)[1]
    _digest(payload, label=tag + " RepoDigest")
    return {
        "source_tag": tag,
        "id": identity["id"],
        "source_revision": identity["source_revision"],
        "repo_digest": matching[0],
    }


def build_record(*, git_commit: str, runtime_ref: str, test_ref: str,
                 invoke=subprocess.run) -> Mapping[str, Any]:
    commit = _digest(git_commit, label="git_commit", git=True)
    runtime = _docker_inspect(runtime_ref, invoke=invoke)
    test = _docker_inspect(test_ref, invoke=invoke)
    for label, image in (("runtime", runtime), ("test", test)):
        if image["source_revision"] != commit:
            raise CertificationStateRefused(
                label + " image was not built from git_commit"
            )
    if runtime["id"] == test["id"]:
        raise CertificationStateRefused("runtime and test image ids are identical")
    return {
        "schema": BUILD_SCHEMA,
        "git_commit": commit,
        "runtime_image": dict(runtime),
        "test_image": dict(test),
    }


def load_build(path: Path) -> Mapping[str, Any]:
    raw = Path(path).read_bytes()
    record = _json_object(raw, label="image build record")
    _mapping(record, label="image build record", fields={
        "schema", "git_commit", "runtime_image", "test_image",
    })
    if record.get("schema") != BUILD_SCHEMA:
        raise CertificationStateRefused("image build record schema is unsupported")
    _digest(record.get("git_commit"), label="build git_commit", git=True)
    for field in ("runtime_image", "test_image"):
        image = _mapping(record.get(field), label=field, fields={
            "ref", "id", "source_revision", "repo_digests",
        })
        if image.get("source_revision") != record["git_commit"]:
            raise CertificationStateRefused(field + " revision differs from build")
        if not isinstance(image.get("id"), str) or not image["id"].startswith(
                "sha256:"):
            raise CertificationStateRefused(field + " id is malformed")
    return record


def verify_build(path: Path, *, invoke=subprocess.run) -> Mapping[str, Any]:
    record = load_build(path)
    for field in ("runtime_image", "test_image"):
        frozen = record[field]
        actual = _docker_inspect(frozen["ref"], invoke=invoke)
        if (actual["id"] != frozen["id"]
                or actual["source_revision"] != frozen["source_revision"]):
            raise CertificationStateRefused(field + " moved after build")
    return record


def promotion_record(*, build_path: Path, runtime_tag: str, test_tag: str,
                     invoke=subprocess.run) -> Mapping[str, Any]:
    build = verify_build(build_path, invoke=invoke)
    runtime = _promoted_identity(runtime_tag, invoke=invoke)
    test = _promoted_identity(test_tag, invoke=invoke)
    for field, promoted, frozen in (
        ("runtime", runtime, build["runtime_image"]),
        ("test", test, build["test_image"]),
    ):
        if (promoted["id"] != frozen["id"]
                or promoted["source_revision"] != build["git_commit"]):
            raise CertificationStateRefused(
                field + " promoted image differs from the frozen build"
            )
    if runtime["repo_digest"].rsplit("@", 1)[1] == \
            test["repo_digest"].rsplit("@", 1)[1]:
        raise CertificationStateRefused("runtime and test RepoDigests are identical")
    return {
        "schema": PROMOTION_SCHEMA,
        "git_commit": build["git_commit"],
        "build_record": {
            "path": Path(build_path).as_posix(),
            "sha256": _sha256(Path(build_path).read_bytes()),
        },
        "runtime_image": dict(runtime),
        "test_image": dict(test),
    }


def load_promotion(path: Path) -> Mapping[str, Any]:
    record = _json_object(Path(path).read_bytes(), label="image promotion record")
    _mapping(record, label="image promotion record", fields={
        "schema", "git_commit", "build_record", "runtime_image", "test_image",
    })
    if record.get("schema") != PROMOTION_SCHEMA:
        raise CertificationStateRefused("image promotion schema is unsupported")
    commit = _digest(record.get("git_commit"), label="promotion git_commit", git=True)
    build_binding = _mapping(record.get("build_record"), label="build binding",
                             fields={"path", "sha256"})
    build_path = Path(build_binding.get("path", ""))
    if (not build_path.is_file()
            or _sha256(build_path.read_bytes()) != build_binding.get("sha256")):
        raise CertificationStateRefused("frozen image build record moved")
    build = load_build(build_path)
    if build["git_commit"] != commit:
        raise CertificationStateRefused("build and promotion commits differ")
    for field in ("runtime_image", "test_image"):
        image = _mapping(record.get(field), label=field, fields={
            "source_tag", "id", "source_revision", "repo_digest",
        })
        if image.get("source_revision") != commit:
            raise CertificationStateRefused(field + " revision differs")
        ref = image.get("repo_digest")
        if not isinstance(ref, str) or "@sha256:" not in ref:
            raise CertificationStateRefused(field + " RepoDigest is malformed")
        _digest(ref.rsplit("@sha256:", 1)[1], label=field + " RepoDigest")
    return record


def verify_promotion(path: Path, *, git_commit: str,
                     invoke=subprocess.run) -> Mapping[str, Any]:
    record = load_promotion(path)
    if record["git_commit"] != _digest(
            git_commit, label="git_commit", git=True):
        raise CertificationStateRefused("promotion belongs to another Git commit")
    for field in ("runtime_image", "test_image"):
        frozen = record[field]
        actual = _docker_inspect(frozen["repo_digest"], invoke=invoke)
        if (actual["id"] != frozen["id"]
                or actual["source_revision"] != record["git_commit"]
                or frozen["repo_digest"] not in actual["repo_digests"]):
            raise CertificationStateRefused(
                field + " immutable image no longer matches promotion"
            )
    return record


def baseline_binding(path: Path) -> Mapping[str, Any]:
    path = Path(path)
    raw = path.read_bytes()
    manifest = _json_object(raw, label="certified baseline manifest")
    if (manifest.get("schema") != "sentinel.certification_manifest/2"
            or manifest.get("lifecycle") != "FINALIZED"
            or manifest.get("verdict") != "PASS"
            or manifest.get("failures") != []
            or manifest.get("git_tree_clean") is not True):
        raise CertificationStateRefused(
            "closure baseline is not clean FINALIZED/PASS evidence"
        )
    return {
        "path": path.as_posix(),
        "sha256": _sha256(raw),
        "git_commit": _digest(
            manifest.get("git_commit"), label="baseline git_commit", git=True
        ),
        "distributions_hash": _digest(
            manifest.get("distributions_hash"),
            label="baseline distributions_hash",
        ),
        "requirements_lock_sha256": _digest(
            manifest.get("requirements_lock_sha256"),
            label="baseline requirements_lock_sha256",
        ),
    }


def _target(identity_path: Path, lock_path: Path, git_commit: str
            ) -> Mapping[str, str]:
    identity = _json_object(Path(identity_path).read_bytes(), label="host identity")
    environment = _mapping(identity.get("environment"), label="host environment")
    lock_sha = _sha256(Path(lock_path).read_bytes())
    image_lock = environment.get("image_lock_sha256")
    if image_lock != lock_sha:
        raise CertificationStateRefused("identity image lock differs from checkout")
    return {
        "git_commit": _digest(git_commit, label="target git_commit", git=True),
        "distributions_hash": _digest(
            environment.get("distributions_hash"),
            label="target distributions_hash",
        ),
        "requirements_lock_sha256": lock_sha,
    }


def _eligible_manifests(art: Path) -> Sequence[Path]:
    eligible = []
    for path in sorted(Path(art).glob("manifest-*.json")):
        try:
            baseline_binding(path)
        except (OSError, CertificationStateRefused):
            continue
        eligible.append(path)
    return eligible


def transition_binding(path: Path) -> Mapping[str, Any]:
    path = Path(path)
    raw = path.read_bytes()
    transition = _json_object(raw, label="closure transition")
    _mapping(transition, label="closure transition", fields={
        "schema", "status", "baseline", "target", "review",
    })
    if transition.get("schema") != TRANSITION_SCHEMA \
            or transition.get("status") != "REVIEWED":
        raise CertificationStateRefused("closure transition is not REVIEWED")
    baseline = _mapping(transition.get("baseline"), label="transition baseline")
    target = _mapping(transition.get("target"), label="transition target")
    review = _mapping(transition.get("review"), label="transition review",
                      fields={"reviewer", "reason", "reviewed_at_utc"})
    if any(not isinstance(review.get(field), str) or not review[field].strip()
           for field in review):
        raise CertificationStateRefused("closure transition review is incomplete")
    return {
        "path": path.as_posix(),
        "sha256": _sha256(raw),
        "baseline": dict(baseline),
        "target": dict(target),
        "review": dict(review),
    }


def validate_closure_context(*, art: Path, identity_path: Path,
                             lock_path: Path, git_commit: str,
                             baseline_path: object = None,
                             transition_path: object = None
                             ) -> Mapping[str, Any]:
    target = _target(identity_path, lock_path, git_commit)
    if baseline_path is None:
        existing = _eligible_manifests(art)
        if existing:
            raise CertificationStateRefused(
                "certified evidence exists; name --certified-baseline explicitly: "
                + ", ".join(path.as_posix() for path in existing)
            )
        if transition_path is not None:
            raise CertificationStateRefused(
                "a closure transition cannot exist without a certified baseline"
            )
        return {"baseline": None, "transition": None, "target": dict(target)}

    baseline = baseline_binding(Path(str(baseline_path)))
    changed = any(
        baseline[field] != target[field]
        for field in ("distributions_hash", "requirements_lock_sha256")
    )
    if not changed:
        if transition_path is not None:
            raise CertificationStateRefused(
                "closure is unchanged; a transition record is not applicable"
            )
        return {"baseline": dict(baseline), "transition": None,
                "target": dict(target)}
    if transition_path is None:
        raise CertificationStateRefused(
            "dependency closure moved; a reviewed transition record is required"
        )
    transition = transition_binding(Path(str(transition_path)))
    if transition["baseline"] != baseline or transition["target"] != target:
        raise CertificationStateRefused(
            "closure transition does not bind this baseline and target"
        )
    return {"baseline": dict(baseline), "transition": dict(transition),
            "target": dict(target)}


def review_transition(*, baseline_path: Path, identity_path: Path,
                      lock_path: Path, git_commit: str, reviewer: str,
                      reason: str, reviewed_at: object = None
                      ) -> Mapping[str, Any]:
    if not reviewer.strip() or not reason.strip():
        raise CertificationStateRefused("reviewer and reason are required")
    baseline = baseline_binding(baseline_path)
    target = _target(identity_path, lock_path, git_commit)
    if all(baseline[field] == target[field] for field in (
            "distributions_hash", "requirements_lock_sha256")):
        raise CertificationStateRefused("closure did not change")
    timestamp = reviewed_at or datetime.now(timezone.utc)
    return {
        "schema": TRANSITION_SCHEMA,
        "status": "REVIEWED",
        "baseline": dict(baseline),
        "target": dict(target),
        "review": {
            "reviewer": reviewer.strip(),
            "reason": reason.strip(),
            "reviewed_at_utc": timestamp.isoformat().replace("+00:00", "Z"),
        },
    }


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CertificationStateRefused("current Git commit is unavailable") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    operations = parser.add_subparsers(dest="operation", required=True)

    build = operations.add_parser("capture-build")
    build.add_argument("--git-commit", required=True)
    build.add_argument("--runtime-ref", required=True)
    build.add_argument("--test-ref", required=True)
    build.add_argument("--output", type=Path, required=True)

    verify = operations.add_parser("verify-build")
    verify.add_argument("--record", type=Path, required=True)

    promote = operations.add_parser("capture-promotion")
    promote.add_argument("--build-record", type=Path, required=True)
    promote.add_argument("--runtime-tag", required=True)
    promote.add_argument("--test-tag", required=True)
    promote.add_argument("--output", type=Path, required=True)

    resolve = operations.add_parser("resolve-promotion")
    resolve.add_argument("--record", type=Path, required=True)
    resolve.add_argument("--git-commit", required=True)
    resolve.add_argument("--kind", choices=("runtime", "test"), required=True)

    check = operations.add_parser("check-closure")
    check.add_argument("--art", type=Path, required=True)
    check.add_argument("--identity", type=Path, required=True)
    check.add_argument("--lock", type=Path, required=True)
    check.add_argument("--git-commit", required=True)
    check.add_argument("--baseline", type=Path)
    check.add_argument("--transition", type=Path)

    review = operations.add_parser("review-transition")
    review.add_argument("--baseline", type=Path, required=True)
    review.add_argument("--identity", type=Path, required=True)
    review.add_argument("--lock", type=Path, required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reason", required=True)
    review.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: object = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "capture-build":
            record = build_record(
                git_commit=args.git_commit, runtime_ref=args.runtime_ref,
                test_ref=args.test_ref,
            )
            write_no_clobber(record, args.output)
        elif args.operation == "verify-build":
            verify_build(args.record)
        elif args.operation == "capture-promotion":
            record = promotion_record(
                build_path=args.build_record, runtime_tag=args.runtime_tag,
                test_tag=args.test_tag,
            )
            write_no_clobber(record, args.output)
        elif args.operation == "resolve-promotion":
            record = verify_promotion(
                args.record, git_commit=args.git_commit
            )
            print(record[args.kind + "_image"]["repo_digest"])
        elif args.operation == "check-closure":
            context = validate_closure_context(
                art=args.art, identity_path=args.identity, lock_path=args.lock,
                git_commit=args.git_commit, baseline_path=args.baseline,
                transition_path=args.transition,
            )
            print("closure_context:" + _sha256(canonical_bytes(context)))
        else:
            record = review_transition(
                baseline_path=args.baseline, identity_path=args.identity,
                lock_path=args.lock, git_commit=_git_commit(),
                reviewer=args.reviewer, reason=args.reason,
            )
            write_no_clobber(record, args.output)
    except (CertificationStateRefused, OSError) as exc:
        print("CERTIFICATION STATE REFUSED: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
