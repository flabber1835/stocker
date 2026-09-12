"""Preserve complete or failed certification evidence on the research branch."""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import urllib.request

REPO = "flabber1835/stocker"
BRANCH = "research/champion-certification-20y-v1"
PREFIX = "research/champion-certification-20y-v1/results"


def api(path, data=None, method=None):
    request = urllib.request.Request("https://api.github.com/repos/" + REPO + path,
        data=None if data is None else json.dumps(data).encode(),
        method=method or ("GET" if data is None else "POST"),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def finalize(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    result_path = root / "RESULT.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    failure = root / "FAILURE.json"
    status = result["status"] if result and not failure.exists() else "INCOMPLETE_OR_FAILED"
    lines = ["# Twenty-year champion certification and PIT composition", "", f"Status: **{status}**.", ""]
    if result:
        lines += ["| Window | CAGR | Max drawdown | Sharpe | Ending wealth |",
                  "|---|---:|---:|---:|---:|"]
        for window in ("5", "10", "15", "20"):
            m = result["metrics"][window]
            lines.append(f"| {window} years | {m['cagr']:.2%} | {m['max_drawdown']:.2%} | "
                         f"{m['sharpe_daily_252']:.3f} | {m['ending_multiple']:.4f}× |")
        c = result["checks"]["composition"]
        lines += ["", f"Composition: {c['measured_sessions']:,} measured sessions, "
                  f"{c['composition_rows']:,} rows, {c['unique_securities']:,} distinct held securities.",
                  f"Carried-mark holding days: {c['carried_mark_holding_days']:,}; "
                  f"unknown canonical-type holding days: {c['unknown_canonical_type_holding_days']:,}.",
                  "", "Fresh Core hashes, frozen champion daily decisions, compact/reference comparisons, "
                  "controller/accounting restarts and composition checks passed."]
    if failure.exists():
        f = json.loads(failure.read_text())
        lines += ["", f"Failure: `{f.get('error_type', 'workflow')}` — {f.get('error', 'see logs')}"]
    lines += ["", "Portfolio export: `portfolio-composition.csv.gz`; daily reconciliation: "
              "`portfolio-sessions.csv.gz`; controller replay: `champion-daily.csv.gz`.",
              "", "Weights include Core cash, dividend receivables and the complementary Treasury-bill sleeve. "
              "Effective and next-target model weights are separately labelled. Stock tickers use each "
              "session's canonical identity metadata. These are scalar strategy model weights.",
              "", "The pinned reconstructed PIT corpus, reviewed classification overlay, terminal economics "
              "and any carried marks remain part of the recorded evidence. This is research replay certification. "
              "Production certification and promotion remain separate; prior economic-preservation and "
              "robustness verdicts remain FAIL.", ""]
    (root / "SUMMARY.md").write_text("\n".join(lines))
    checksums = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(root.rglob("*")) if p.is_file() and p.name != "SHA256.json"}
    (root / "SHA256.json").write_text(json.dumps(checksums, indent=2, sort_keys=True) + "\n")


def payloads(root):
    selected = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        name = str(p.relative_to(root))
        if p.suffix not in (".csv", ".json", ".md", ".py", ".txt", ".log"):
            continue
        raw = p.read_bytes()
        if p.suffix in (".csv", ".log"):
            selected[name + ".gz"] = gzip.compress(raw, mtime=0)
        else:
            selected[name] = raw
    selected["PUBLISHED_SHA256.json"] = (json.dumps({k: hashlib.sha256(v).hexdigest()
        for k, v in selected.items()}, indent=2, sort_keys=True) + "\n").encode()
    return selected


def publish(root, pr_number):
    finalize(root)
    suffix = f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    directory = f"{PREFIX}/{suffix}"
    parent = api("/git/ref/heads/" + BRANCH)["object"]["sha"]
    comparison = api(f"/compare/{os.environ['GITHUB_SHA']}...{parent}")
    if comparison["status"] not in ("ahead", "identical"):
        raise RuntimeError("publication branch does not descend from the launch")
    tree = api("/git/commits/" + parent)["tree"]["sha"]
    entries = []
    for name, data in payloads(root).items():
        blob = api("/git/blobs", {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        entries.append(dict(path=directory + "/" + name, mode="100644", type="blob", sha=blob["sha"]))
    new_tree = api("/git/trees", {"base_tree": tree, "tree": entries})["sha"]
    commit = api("/git/commits", {"tree": new_tree, "parents": [parent],
        "message": f"Record champion certification and PIT composition ({suffix})"})["sha"]
    api("/git/refs/heads/" + BRANCH, {"sha": commit, "force": False}, "PATCH")
    url = f"https://github.com/{REPO}/blob/{commit}/{directory}/SUMMARY.md"
    body = f"Twenty-year champion certification evidence: [results and PIT portfolio weights]({url}).\n\n"
    body += (root / "SUMMARY.md").read_text()
    for number in sorted({349, 350, pr_number}):
        if number:
            api(f"/issues/{number}/comments", {"body": body})
    print("[PUBLISHED] " + json.dumps({"commit": commit, "url": url}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--pr-number", type=int, default=0)
    args = parser.parse_args()
    if args.publish:
        publish(args.root, args.pr_number)
    else:
        finalize(args.root)
