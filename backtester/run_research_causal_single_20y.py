#!/usr/bin/env python3
"""Execute one full-window instrumented retained-research causal replay."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PINNED_MAIN_ROOT = ROOT / "main-src"
if PINNED_MAIN_ROOT.is_dir() and str(PINNED_MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PINNED_MAIN_ROOT))

from backtester.research_causal_instrumentation import instrument_research_source


WARMUP_START = "2006-01-03"
MEASUREMENT_START = "2006-07-31"
FULL_END = "2026-07-31"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_files(paths: Iterable[Path]) -> None:
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"causal replay did not emit required files: {missing}")


def _set_or_remove(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _expose_generated_child_runtime() -> None:
    ordered = [str(ROOT)]
    if PINNED_MAIN_ROOT.is_dir():
        ordered.append(str(PINNED_MAIN_ROOT))
    existing = os.environ.get("PYTHONPATH", "")
    ordered.extend(part for part in existing.split(os.pathsep) if part)
    os.environ["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(ordered))


def _inject_poison_dtype_compat(source: str) -> str:
    """Preserve pandas dtypes and normalize terminal-domain poison evidence."""
    seam = "    _CANONICAL=CausalPITDataset("
    if source.count(seam) != 1:
        raise RuntimeError(
            "poison dtype compatibility expected one canonical dataset seam"
        )
    patch = """
    _CAUSAL_ORIGINAL_POISON_OBSERVATIONS=CausalPITDataset._poison_observations
    def _causal_dtype_safe_poison_observations(self, frame):
        frame=frame.copy()
        for _causal_bool_column in ('security_type_eligible','listing_active','tradeable','metadata_admitted'):
            if _causal_bool_column in frame.columns:
                frame[_causal_bool_column]=frame[_causal_bool_column].astype(bool)
        for _causal_text_column in ('issuer_id','issuer_source','security_type','security_type_source','sic','ff12','sector_source','identity_source'):
            if _causal_text_column in frame.columns:
                frame[_causal_text_column]=frame[_causal_text_column].astype(object)
        return _CAUSAL_ORIGINAL_POISON_OBSERVATIONS(self,frame)
    CausalPITDataset._poison_observations=_causal_dtype_safe_poison_observations
    _CAUSAL_ORIGINAL_POISON_MANIFEST=CausalPITDataset.poison_manifest
    def _causal_semantic_poison_manifest(self):
        payload=_CAUSAL_ORIGINAL_POISON_MANIFEST(self)
        changed=dict(payload.get('changed_rows') or {})
        terminal_actions=int(changed.get('terminal_action_rows',0))
        if int(changed.get('terminal_rows',0)) <= 0 and terminal_actions > 0:
            changed['terminal_rows']=terminal_actions
            payload=dict(payload)
            payload['changed_rows']=changed
            payload['terminal_rows_source']='terminal_action_rows'
            payload.pop('manifest_sha256',None)
            payload['manifest_sha256']=sha256_json(payload)
        return payload
    CausalPITDataset.poison_manifest=_causal_semantic_poison_manifest
""".strip("\n")
    result = source.replace(seam, patch + "\n" + seam, 1)
    compile(result, "<generated-causal-research-replay>", "exec")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--view", choices=("baseline", "prefix", "poison"), required=True)
    parser.add_argument("--cutoff")
    parser.add_argument("--poison-seed", type=int, default=314159)
    args = parser.parse_args()

    if args.view in {"prefix", "poison"} and not args.cutoff:
        parser.error(f"--cutoff is required for {args.view}")
    if args.view == "baseline" and args.cutoff:
        parser.error("baseline view does not accept --cutoff")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    trace_path = output / "causal-trace.jsonl.gz"
    guard_path = output / "runtime-guard-report.json"
    generated_path = output / "generated-research-replay.py"

    os.environ["CANONICAL_PIT_DATASET"] = str(args.canonical_dataset.resolve())
    os.environ["CERTIFICATION_WARMUP_START"] = WARMUP_START
    os.environ["CERTIFICATION_END_SESSION"] = args.cutoff if args.view == "prefix" else FULL_END
    os.environ["CAUSAL_DATASET_MODE"] = args.view
    _set_or_remove("CAUSAL_CUTOFF", args.cutoff)
    os.environ["CAUSAL_POISON_SEED"] = str(args.poison_seed)
    os.environ["CAUSAL_TRACE_PATH"] = str(trace_path)
    os.environ["CAUSAL_GUARD_REPORT_PATH"] = str(guard_path)
    os.environ["CAUSAL_GENERATED_SOURCE_PATH"] = str(generated_path)
    os.environ["CERTIFICATION_STRICT_PIT"] = "1"
    _expose_generated_child_runtime()

    import backtester.run_research_strict_pit_20y as replay

    base_transform = replay.corrected.transformed_source

    def causal_transform(mode: str, child_output: Path) -> str:
        source = instrument_research_source(base_transform(mode, child_output))
        if args.view == "poison":
            source = _inject_poison_dtype_compat(source)
        generated_path.write_text(source, encoding="utf-8")
        return source

    replay.corrected.transformed_source = causal_transform
    original_argv = list(sys.argv)
    try:
        sys.argv = [
            original_argv[0],
            "--mode",
            "fullpit",
            "--output",
            str(output),
        ]
        rc = int(replay.main())
    finally:
        sys.argv = original_argv
    if rc != 0:
        return rc

    _required_files(
        (
            trace_path,
            guard_path,
            generated_path,
            output / "daily.csv.gz",
            output / "summary.json",
            output / "metadata_authority_audit.json",
        )
    )
    guard = json.loads(guard_path.read_text(encoding="utf-8"))
    if guard.get("status") != "PASS":
        raise RuntimeError("runtime causal guard did not pass")
    expected_sessions = int(guard["expected_sessions"])
    if int(guard.get("trace_rows", -1)) != expected_sessions:
        raise RuntimeError(
            f"causal trace rows {guard.get('trace_rows')} != expected {expected_sessions}"
        )

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": "backtester.research-causal-single-run/2",
        "status": "PASS",
        "scope": "20-year",
        "view": args.view,
        "cutoff": args.cutoff,
        "poison_seed": args.poison_seed if args.view == "poison" else None,
        "warmup_start": WARMUP_START,
        "measurement_start": MEASUREMENT_START,
        "end_session": args.cutoff if args.view == "prefix" else FULL_END,
        "dataset_hash": guard.get("dataset_hash"),
        "dataset_id": guard.get("dataset_id"),
        "research_embedded_commit": summary.get("research_embedded_commit"),
        "trace_rows": guard.get("trace_rows"),
        "trace_sha256": guard.get("trace_sha256"),
        "generated_source_sha256": sha256_file(generated_path),
        "runtime_guard_report_sha256": sha256_file(guard_path),
        "poison": guard.get("poison"),
    }
    manifest_path = output / "causal-run-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"[20Y CAUSAL RUN PASS] view={args.view} cutoff={args.cutoff} "
        f"sessions={manifest['trace_rows']} trace={manifest['trace_sha256']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
