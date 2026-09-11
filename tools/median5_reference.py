#!/usr/bin/env python3
"""Stage and verify the independent research dependency tree from Git pins."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

FORMAL = "27bb992087182c42c3c051e62bf837895f5d2ab7"
CLASSIFIER = "ba74e79490beb8950611b1d17f5d124833b3d91e"
RESEARCH = "1c66096c1e3bd650233c630d4e9f71104ac8fc32"
DEPENDENCIES_SHA = "d4b1ac0f8da7eaf8010d37575bdc271e5d480e3edc354480d3a847547b91fe0b"

CLASSIFIER_FILES = (
    "backtester/research_champion_corrected_classification.py",
    "backtester/research_champion_best_effort_classification.py",
    "backtester/data/champion-best-effort-security-types-v1.csv",
    "backtester/data/champion-best-effort-security-types-v1-summary.json",
    "backtester/data/champion-reviewed-security-types-v1.csv",
    "backtester/data/champion-historical-security-type-corrections-v1.csv",
)
RESEARCH_FILES = tuple("backtester/" + name for name in (
    "champion_economic_prefix_audit.py",
    "champion_full_classification_control.py",
    "champion_security_truth_audit_v2.py",
    "champion_security_truth_overlay_v2.py",
    "champion_final_security_truth.py",
    "champion_final_truth_corpus_validator.py",
    "production_equivalent_economic_overlay.py",
    "champion_production_equivalent_build.py",
    "champion_production_equivalent_final_replay.py",
    "data/champion-security-truth-factual-batch-v2.json",
)) + ("research/champion-economic-integrity/security-truth/manual-review",)


def digest(root: Path) -> str:
    members = [{"path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in sorted(root.rglob("*"))
               if path.is_file() and "__pycache__" not in path.parts]
    return hashlib.sha256(json.dumps(members, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def verify(root: Path) -> str:
    actual = digest(root)
    if actual != DEPENDENCIES_SHA:
        raise ValueError(f"Median-5 research dependencies changed: {actual}")
    return actual


def stage(repo: Path, output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise ValueError("research staging output must be empty")
    # Resolve every source before writing anything. Missing pins require an
    # ordinary fetch; this helper never changes branches or network settings.
    for commit in (FORMAL, CLASSIFIER, RESEARCH):
        found = subprocess.check_output(
            ["git", "rev-parse", commit + "^{commit}"], cwd=repo, text=True).strip()
        if found != commit:
            raise ValueError("research source pin did not resolve exactly")
    output.mkdir(parents=True, exist_ok=True)
    for commit, paths in ((FORMAL, ("backtester",)),
                          (CLASSIFIER, CLASSIFIER_FILES),
                          (RESEARCH, RESEARCH_FILES)):
        data = subprocess.check_output(["git", "archive", commit, "--", *paths], cwd=repo)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(output, filter="data")
    verify(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_only:
        stage(args.repo.resolve(), args.output.resolve())
    print(json.dumps({"status": "VERIFIED", "dependency_sha256": verify(args.output),
                      "formal_commit": FORMAL, "classifier_commit": CLASSIFIER,
                      "research_commit": RESEARCH}, indent=2))


if __name__ == "__main__":
    main()
