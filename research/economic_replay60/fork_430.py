from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--old-runtime", type=Path, required=True)
    parser.add_argument("--old-pointer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()

    if args.revision != "ee23c894c97a2c4023654ce3a56a62728f5b061e":
        raise ValueError("fork requires reviewed PR430 revision")
    if args.output.exists():
        raise ValueError("fork output already exists")
    old_manifest = json.loads((args.old_runtime / "research/bounded_20y/production-source.json").read_text())
    if old_manifest["revision"] != "da7b64a9429c9c73fb7efac90c8d4a5decb39e13":
        raise ValueError("unexpected predecessor source")
    for name, expected in old_manifest["files"].items():
        if sha256(args.old_runtime / name) != expected:
            raise ValueError("predecessor source changed: " + name)
    manifest_path = args.runtime / "research/bounded_20y/production-source.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["revision"] = args.revision
    for relative in manifest["files"]:
        manifest["files"][relative] = sha256(args.runtime / relative)
    changed_files = {name for name, value in manifest["files"].items()
                     if old_manifest["files"].get(name) != value}
    if set(manifest["files"]) != set(old_manifest["files"]) or changed_files != {
            "sentinel/core/kernel.py", "sentinel/core/spinoffs.py",
            "shared/stock_strategy_shared/wealth_core/ledger.py"}:
        raise ValueError(f"unexpected production source changes: {changed_files}")
    dump(manifest_path, manifest)

    sys.argv = [sys.argv[0], "--harness", str(args.runtime)]
    sys.path[:0] = [str(args.runtime / "shared"), str(args.runtime)]
    from research.economic_replay60 import run
    from sentinel.core.session import SessionState
    from sentinel.strategy import production_strategy

    binding = {
        "production": run.PRODUCTION_REVISION,
        "production_manifest": run.digest(manifest),
        "dataset": run.BASE_DATASET_SHA256,
        "reference": run.REFERENCE_SHA256,
        "harness": {
            name: run.sha256(args.runtime / "research/bounded_20y" / name)
            for name in ("january.py", "run.py", "inputs.py", "supplement.py")
        },
        "capital": "100000",
        "origin": run.ORIGIN,
        "measurement": run.START,
        "classification_intervals": run.OVERLAY_SHA256,
        "economic_runner": run.sha256(args.runtime / "research/economic_replay60/run.py"),
        "economic_inputs": run.sha256(args.runtime / "research/economic_replay60/inputs.py"),
    }

    pointer = json.loads(args.old_pointer.read_text(encoding="utf-8"))
    old_path = Path(pointer["path"])
    if sha256(old_path) != pointer["sha256"]:
        raise ValueError("old checkpoint bytes changed")
    with gzip.open(old_path, "rt", encoding="utf-8") as source:
        packet = json.load(source)
    if (packet["binding"]["production"] != old_manifest["revision"]
            or packet["binding"]["production_manifest"] != run.digest(old_manifest)):
        raise ValueError("checkpoint predecessor binding differs")
    if pointer["last_session"] != "2015-06-30":
        raise ValueError("fork requires the pre-Baxter checkpoint")
    old_state = SessionState.from_dict(packet["state"])
    if old_state.state_hash != packet["state_sha256"]:
        raise ValueError("old checkpoint state commitment differs")
    if old_state.last_processed_session != pointer["last_session"]:
        raise ValueError("old checkpoint session differs")

    _, new_identity = production_strategy()
    old_identity = packet["state"]["strategy_identity"]
    changed = {
        key: {"old": old_identity.get(key), "new": new_identity.get(key)}
        for key in sorted(set(old_identity) | set(new_identity))
        if old_identity.get(key) != new_identity.get(key)
    }
    if set(changed) != {"wealth_core_source_sha256", "data_semantics_source_sha256"}:
        raise ValueError(f"unexpected strategy identity changes: {changed}")

    migrated_state = copy.deepcopy(packet["state"])
    migrated_state["strategy_identity"] = new_identity
    state = SessionState.from_dict(migrated_state)
    migrated = copy.deepcopy(packet)
    migrated["binding"] = binding
    migrated["state"] = migrated_state
    migrated["state_sha256"] = state.state_hash
    assert {k:v for k,v in migrated_state.items() if k != "strategy_identity"} == {
        k:v for k,v in packet["state"].items() if k != "strategy_identity"}
    for key in ("economics", "statistics", "metadata", "sectors", "factors", "applied_supplements", "total_sessions"):
        assert migrated[key] == packet[key], key
    migrated["migration"] = {
        "kind": "explicit_analytical_source_fork",
        "old_pointer": str(args.old_pointer.resolve()),
        "old_checkpoint_sha256": pointer["sha256"],
        "old_state_sha256": old_state.state_hash,
        "new_state_sha256": state.state_hash,
        "last_processed_session": state.last_processed_session,
        "production_revision": args.revision,
        "identity_changes": changed,
        "history_rewritten": False,
        "scope": "mixed-source analytical continuation; not certification",
        "changed_production_files": sorted(changed_files),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    new_pointer = run.write_checkpoint(args.output, migrated)
    dump(args.output / "migration.json", migrated["migration"] | {
        "new_checkpoint_sha256": new_pointer["sha256"],
        "new_checkpoint_path": new_pointer["path"],
        "production_manifest_sha256": run.sha256(manifest_path),
    })
    verified_packet, verified_state = run.read_checkpoint(
        args.output / "latest-checkpoint.json", binding
    )
    print(json.dumps({
        "status": "MIGRATION_VERIFIED",
        "last_session": verified_state.last_processed_session,
        "state_sha256": verified_packet["state_sha256"],
        "checkpoint_sha256": new_pointer["sha256"],
        "identity_changes": changed,
    }, indent=2))


if __name__ == "__main__":
    main()
