"""Read-only terminal inventory. No Core, controller, account or network imports.

This is data triage, not a terminal-skipping backtest. All outputs are private.
An observed reference raises priority; its absence never proves unreachability.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def native(path: str | Path) -> Path:
    value = str(Path(path).absolute())
    return Path("\\\\?\\" + value) if os.name == "nt" and not value.startswith("\\\\?\\") else Path(value)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def security_refs(value, targets: set[str]) -> set[str]:
    """Literal identity references only. This function assigns no ownership meaning."""
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in targets:
                found.add(str(key))
            found.update(security_refs(child, targets))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(security_refs(child, targets))
    elif isinstance(value, (str, int)) and str(value) in targets:
        found.add(str(value))
    return found


def record_refs(refs, arm: str, role: str, session: str, ids: set[str], source: str) -> None:
    for sid in ids:
        entry = refs[sid].setdefault(arm, {}).setdefault(role, {"count": 0, "first": session, "last": session, "sources": []})
        entry["count"] += 1
        entry["first"] = min(entry["first"], session)
        entry["last"] = max(entry["last"], session)
        if source not in entry["sources"]:
            entry["sources"].append(source)


def evidence_scan(config, targets):
    refs = defaultdict(dict)
    coverage = {}
    for arm, spec in sorted(config["candidates"].items()):
        root = native(spec["root"])
        cp_path = root / "book/checkpoint.json.gz"
        cp = load(cp_path)
        state = cp["run"]["state"]
        session = cp["source_cursor"]
        item = {"root": str(root), "checkpoint_file_sha256": file_hash(cp_path), "outer_sha256": cp["sha256"],
                "session": session, "measured_closes": cp["completed"], "journals": {}, "supplementary": {},
                "all_historical_checkpoints_rescanned": False, "basis_is_not_inferred_from_other_arms": True}
        core = state.get("wealth_core", {}) or {}
        episodes = core.get("episodes", {})
        for episode in episodes.values() if isinstance(episodes, dict) else episodes:
            if isinstance(episode, dict) and float(episode.get("current_shares", 0)) > 0:
                record_refs(refs, arm, "OWNED_AT_CHECKPOINT", session,
                            security_refs(episode.get("security_id"), targets), "checkpoint.wealth_core.episodes")
        record_refs(refs, arm, "PENDING_AT_CHECKPOINT", session, security_refs(state.get("pending", []), targets), "checkpoint.pending")
        record_refs(refs, arm, "LEADERSHIP_AT_CHECKPOINT", session,
                    security_refs((state.get("median5") or {}).get("selected", []), targets), "checkpoint.median5.selected")
        record_refs(refs, arm, "CORE_STATE_REFERENCE", session, security_refs(core, targets), "checkpoint.wealth_core")
        # Feed.series and median5.peer_keys are universe membership, not selection.
        for name in ("formation", "daily", "watch", "monthly"):
            choices = [root / f"book/{name}.jsonl", root / f"book/{name}.jsonl.gz"]
            path = next((p for p in choices if p.exists()), None)
            commitment = cp["journals"][name]
            if path is None:
                item["journals"][name] = {"available": False, "committed_bytes": commitment["bytes"], "coverage_gap": True}
                continue
            h = hashlib.sha256()
            full = hashlib.sha256()
            length = rows = committed_rows = tail_rows = 0
            first = last = None
            with (gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")) as stream:
                for raw in stream:
                    prior_length = length
                    length += len(raw)
                    full.update(raw)
                    if prior_length < commitment["bytes"] < length:
                        raise ValueError(f"partial journal record at commitment: {arm}/{name}")
                    committed = length <= commitment["bytes"]
                    if committed:
                        h.update(raw)
                        committed_rows += 1
                    else:
                        tail_rows += 1
                    value = json.loads(raw)
                    date = str(value.get("session", value.get("unchanged_through", "UNKNOWN")))
                    first = date if first is None else first
                    last = date
                    role = "COMMITTED_JOURNAL_REFERENCE" if committed else "UNSENT_JOURNAL_REFERENCE"
                    record_refs(refs, arm, role, date, security_refs(value, targets), f"book/{name}")
                    if name in ("formation", "daily"):
                        intents = value.get("evidence", {}).get("wealth_core", {}).get("intents", [])
                        record_refs(refs, arm, "COMMITTED_INTENT_REFERENCE" if committed else "UNSENT_INTENT_REFERENCE",
                                    date, security_refs(intents, targets), f"book/{name}.wealth_core.intents")
                    rows += 1
            if length < commitment["bytes"] or h.hexdigest() != commitment["prefix_sha256"]:
                raise ValueError(f"journal commitment mismatch: {arm}/{name}")
            item["journals"][name] = {"available": True, "rows": rows, "first": first, "last": last,
                "committed_rows": committed_rows, "unsent_rows": tail_rows, "uncompressed_bytes": length,
                "full_sha256": full.hexdigest(), "committed_bytes": commitment["bytes"], "prefix_sha256": h.hexdigest(),
                "committed_prefix_verified": True, "tail_bytes": length - commitment["bytes"]}
        for name, role in (("correlation-inputs.jsonl.gz", "HELD_IN_CORRELATION_SNAPSHOT"),
                           ("uncertainty-certificate.jsonl", "LEADERSHIP_CERTIFICATE_REFERENCE")):
            path = root / name
            if not path.exists():
                item["supplementary"][name] = {"available": False, "coverage_gap": True}
                continue
            rows = 0
            h = hashlib.sha256()
            with (gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")) as stream:
                for raw in stream:
                    h.update(raw)
                    value = json.loads(raw)
                    material = value.get("material", {})
                    data = material.get("held", []) if role == "HELD_IN_CORRELATION_SNAPSHOT" else material.get("rows", [])
                    date = value.get("session", material.get("session", "UNKNOWN"))
                    suffix = "_AFTER_COMMITTED_CURSOR" if date > session else ""
                    record_refs(refs, arm, role + suffix, date, security_refs(data, targets), name)
                    rows += 1
            item["supplementary"][name] = {"available": True, "rows": rows, "uncompressed_sha256": h.hexdigest(),
                "classification": "retained observation references; supplementary chain not independently readmitted here"}
        result = root / "book/result.json"
        if result.exists():
            value = load(result)
            item["result_sha256"] = file_hash(result)
            item["actual_reported_status"] = {k: v for k, v in value.items() if k != "error"}
            item["error_tail"] = value.get("error", "")[-3000:]
        coverage[arm] = item
        print(json.dumps({"stage": "candidate-evidence", "arm": arm, "checkpoint": session,
                          "available_journals": sum(v["available"] for v in item["journals"].values())}), flush=True)
    return dict(refs), coverage


def update_support(support, row, fields):
    date = row[fields["session"]]
    support["rows"] += 1
    support["first"] = support["first"] or date
    support["last"] = date
    for field, output in (("security_type_eligible", "ever_eligible"), ("tradeable", "ever_tradeable"),
                          ("metadata_admitted", "ever_metadata_admitted")):
        support[output] |= row[fields[field]] in ("1", "true", "True")
    for field in ("ticker", "issuer_id", "security_type", "identity_source"):
        support[field + "_values"].add(row[fields[field]])


def anchor_events(events, row, fields):
    """Keep actual nearest rows; no interpolation, session shift or payout inference."""
    date = row[fields["session"]]
    for event in events:
        if date < event["native_session"]:
            event["anchors"]["before"] = row
        elif date == event["native_session"]:
            event["anchors"].setdefault("on", []).append(row)
        elif event["anchors"].get("after") is None:
            event["anchors"]["after"] = row


def source_scan(config, events, out):
    by_sid = defaultdict(list)
    for event in events:
        by_sid[event["security_id"]].append(event)
    support = {sid: {"rows": 0, "first": None, "last": None, "ever_eligible": False, "ever_tradeable": False,
                     "ever_metadata_admitted": False, **{k + "_values": set() for k in
                     ("ticker", "issuer_id", "security_type", "identity_source")}} for sid in by_sid}
    years = []
    started = time.monotonic()
    archive_path = native(config["archive"])
    first_header = None
    with zipfile.ZipFile(archive_path) as archive:
        for year in range(int(config["warmup_start"][:4]), int(config["end"][:4]) + 1):
            name = f"observations-{year}.csv.gz"
            info = archive.getinfo(name)
            before = time.monotonic()
            total = relevant = 0
            with archive.open(name) as compressed, gzip.GzipFile(fileobj=compressed) as expanded:
                reader = csv.reader(io.TextIOWrapper(expanded, encoding="utf-8", newline=""))
                header = next(reader)
                if first_header is None:
                    first_header = header
                elif header != first_header:
                    raise ValueError("observation schema changed across frozen years")
                fields = {name: i for i, name in enumerate(header)}
                si, di = fields["security_id"], fields["session"]
                for row in reader:
                    total += 1
                    if not config["warmup_start"] <= row[di] <= config["end"]:
                        continue
                    sid = row[si]
                    if sid not in by_sid:
                        continue
                    relevant += 1
                    update_support(support[sid], row, fields)
                    anchor_events(by_sid[sid], row, fields)
            item = {"member": name, "gzip_bytes": info.file_size, "zip_crc32": info.CRC,
                    "all_rows": total, "target_rows_in_period": relevant,
                    "seconds": round(time.monotonic() - before, 3), "entire_gzip_stream_read": True}
            years.append(item)
            save(out / "source-scan-progress.json", {"years": years, "complete": False})
            print(json.dumps({"stage": "source-year", **item}), flush=True)
    for sid, value in support.items():
        for key, child in list(value.items()):
            if isinstance(child, set):
                value[key] = sorted(child)
    for event in events:
        event["source_support"] = support[event["security_id"]]
        for key, value in list(event["anchors"].items()):
            if key == "on":
                event["anchors"][key] = [dict(zip(header, row)) for row in value]
            elif value is not None:
                event["anchors"][key] = dict(zip(header, value))
        event["anchor_sha256"] = digest(event["anchors"])
    return {"years": years, "seconds": round(time.monotonic() - started, 3), "complete": True}


def category(event):
    text = " ".join([str(event["native"].get("reference", "")),
                     *(str(v) for row in event["provider_rows"] for v in row.values())]).lower()
    if "contingent" in text or "cvr" in text:
        return "CONTINGENT_RIGHTS"
    if "bankrupt" in text or "liquidat" in text:
        return "BANKRUPTCY_OR_LIQUIDATION_NOT_AUTOMATIC_ZERO"
    if re.search(r"\bunits?\b", text):
        return "UNIT_OR_COMPOSITE_INSTRUMENT"
    if event["native"].get("kind") in ("CONVERSION", "CASH_PLUS_STOCK", "MIXED_MERGER"):
        return "STOCK_OR_MIXED_CONSIDERATION"
    if "delisted" in text and "acquisitionby" not in text:
        return "LISTING_EXIT_WITHOUT_PROVEN_CONSIDERATION"
    return "ACQUISITION_TERMS_OR_OTHER_UNRESOLVED"


def prioritize(event):
    if event.get("known_blockers"):
        return 0, "ACTUAL_RETAINED_BLOCKER"
    roles = {role for arm in event.get("observed_references", {}).values() for role in arm}
    if any("OWNED" in role or "PENDING" in role or "HELD_IN" in role for role in roles):
        return 1, "OBSERVED_OWNERSHIP_OR_PENDING_RELEVANCE"
    if roles:
        return 2, "OBSERVED_SELECTION_INTENT_OR_OTHER_REFERENCE"
    if event["source_support"]["ever_eligible"]:
        return 3, "FROZEN_ELIGIBLE_SOMEWHERE_IN_SCAN"
    if event["source_support"]["rows"]:
        return 4, "SOURCE_SUPPORTED_NO_OBSERVED_ELIGIBLE_ROW"
    return 5, "NO_FROZEN_OBSERVATION_SUPPORT_IN_SCAN"


def complete_native_term(row):
    """Presence triage only; canonical economic validation is deliberately separate."""
    if not row or "INCOMPLETE" in row.get("disposition", ""):
        return False
    required = {"CASH_MERGER": ("cash_per_share",),
                "CONVERSION": ("delivered_security_id", "exchange_ratio"),
                "CASH_PLUS_STOCK": ("delivered_security_id", "exchange_ratio", "cash_per_share"),
                "MIXED_MERGER": ("delivered_security_id", "exchange_ratio", "cash_per_share")}
    return row.get("kind") in required and all(row.get(k) not in (None, "") for k in required[row["kind"]])


def run(config, output):
    started = time.monotonic()
    out = native(output)
    if (out / "inventory.jsonl").exists():
        raise ValueError("refuse overwrite of completed discovery evidence")
    out.mkdir(parents=True, exist_ok=True)
    bundle = native(config["bundle"])
    original = load(bundle / "terminal-schedule.json")
    base = load(bundle / "repaired-base-terminal-schedule.json")
    with gzip.open(bundle / "benchmark.csv.gz", "rt", encoding="utf-8", newline="") as stream:
        sessions = [row["session"] for row in csv.DictReader(stream)]
    if len(set(sessions)) != len(sessions) or sessions != sorted(sessions):
        raise ValueError("benchmark axis is not unique and chronological")
    start_index = sessions.index(config["start"])
    if sessions[start_index - 425] != config["warmup_start"]:
        raise ValueError("warmup must contain exactly 299+126 prior market sessions")
    base_keys = {(v["effective_session"], str(v["security_id"])): v for v in base}
    events = []
    for index, row in enumerate(original):
        date, sid = row["effective_session"], str(row["security_id"])
        if config["warmup_start"] <= date <= config["end"]:
            events.append({"id": f"N{index:05d}", "security_id": sid, "native_session": date,
                           "native": row, "native_row_sha256": digest(row), "anchors": {"before": None, "on": [], "after": None},
                           "base_row": base_keys.get((date, sid)), "phase": "WARMUP" if date < config["start"] else "MEASURED"})
    # Preserve duplicate native records by index, never silently overwrite by SID/date.
    targets = {e["security_id"] for e in events}
    refs, coverage = evidence_scan(config, targets)
    save(out / "candidate-coverage.json", coverage)
    save(out / "observed-references.json", refs)
    basis_path = native(config["effective_p02_basis"])
    basis = load(basis_path)
    if digest(basis["value"]) != basis["sha256"]:
        raise ValueError("effective factual/model basis commitment mismatch")
    facts = basis["value"]["factual_semantics"]
    suppressed = defaultdict(list)
    for row in facts["suppress"]:
        suppressed[(row["session"], str(row["security_id"]))].append(row)
    added = defaultdict(list)
    for row in facts["add"]:
        added[str(row["security_id"])].append(row)
    by_provider_key = defaultdict(list)
    relevant_keys = {(e["native_session"], e["native"].get("ticker", "")) for e in events}
    aliases = defaultdict(list)
    tickers = {key[1] for key in relevant_keys}
    provider_path = native(config["provider_actions"])
    with zipfile.ZipFile(provider_path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError("ambiguous provider actions member")
        with archive.open(members[0]) as binary:
            for row in csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")):
                key = (row["date"], row["ticker"])
                if key in relevant_keys:
                    by_provider_key[key].append(row)
                if row["ticker"] in tickers and row["action"] in {"tickerchangefrom", "tickerchangeto", "related", "relation"}:
                    aliases[row["ticker"]].append(row)
    source = source_scan(config, events, out)
    blockers = config.get("known_blockers", [])
    for event in events:
        sid, date = event["security_id"], event["native_session"]
        event["provider_rows"] = by_provider_key[(date, event["native"].get("ticker", ""))]
        event["provider_alias_history"] = aliases[event["native"].get("ticker", "")]
        event["observed_references"] = refs.get(sid, {})
        event["known_blockers"] = [b for b in blockers if str(b.get("security_id")) == sid
                                   and b.get("native_session", date) == date]
        event["p02_effective_suppressions"] = suppressed.get((date, sid), [])
        event["p02_effective_added_terms_for_security"] = added.get(sid, [])
        event["p02_fact_replacement_available"] = bool(event["p02_effective_suppressions"] and added.get(sid))
        event["p02_repair_is_not_automatically_adopted_by_other_candidates"] = True
        event["native_flagged_incomplete"] = "INCOMPLETE" in event["native"].get("disposition", "")
        event["base_term_fields_present"] = complete_native_term(event["base_row"])
        event["problem_group"] = category(event)
        event["priority"], event["priority_reason"] = prioritize(event)
        event["ticker_reuse_warning"] = len(event["source_support"]["issuer_id_values"]) > 1
        event["listing_exit_is_not_cash_payout"] = event["problem_group"] == "LISTING_EXIT_WITHOUT_PROVEN_CONSIDERATION"
        event["unresolved_or_special_model"] = (event["native_flagged_incomplete"]
            and not event["p02_fact_replacement_available"] and not event["base_term_fields_present"])
    events.sort(key=lambda e: (e["priority"], e["native_session"], e["security_id"], e["id"]))
    with (out / "inventory.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for event in events:
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    queue = [{k: e[k] for k in ("id", "security_id", "native_session", "phase", "priority", "priority_reason",
                              "problem_group", "p02_fact_replacement_available", "known_blockers")}
             | {"ticker": e["native"].get("ticker"), "reference_arms": sorted(e["observed_references"]),
                "ever_eligible": e["source_support"]["ever_eligible"]}
             for e in events if e["unresolved_or_special_model"]]
    save(out / "prioritized-unresolved.json", queue)
    save(out / "effective-p02-basis.json", basis)
    commitments = {name: {"path": str(path), "bytes": path.stat().st_size, "sha256": file_hash(path)} for name, path in {
        "original_schedule": bundle / "terminal-schedule.json", "base_schedule": bundle / "repaired-base-terminal-schedule.json",
        "benchmark": bundle / "benchmark.csv.gz", "provider_actions": provider_path, "observation_archive": native(config["archive"]),
        "effective_p02_basis": basis_path}.items()}
    if commitments["observation_archive"]["sha256"] != config["archive_sha256"]:
        raise ValueError("frozen observation archive differs from admitted base")
    if commitments["provider_actions"]["sha256"] != config["provider_sha256"]:
        raise ValueError("provider archive differs from admitted source")
    summary = {"schema": "research.terminal-discovery/1", "status": "COMPLETE_METADATA_DISCOVERY_NOT_FINANCIAL_REPLAY",
        "created_utc": datetime.now(timezone.utc).isoformat(), "seconds": round(time.monotonic() - started, 3),
        "config_sha256": digest(config), "period": {k: config[k] for k in ("warmup_start", "start", "end")},
        "measured_session_count": len([d for d in sessions if config["start"] <= d <= config["end"]]),
        "native_records": len(events), "native_records_by_phase": dict(Counter(e["phase"] for e in events)),
        "native_flagged_incomplete": sum(e["native_flagged_incomplete"] for e in events),
        "p02_fact_replacements_available": sum(e["p02_fact_replacement_available"] for e in events),
        "unresolved_queue": len(queue), "unresolved_by_priority": dict(Counter(e["priority"] for e in queue)),
        "unresolved_by_problem": dict(Counter(e["problem_group"] for e in queue)),
        "candidate_count": len(coverage), "candidate_missing_journal_files": sum(not j["available"] for c in coverage.values() for j in c["journals"].values()),
        "source_scan": source, "commitments": commitments, "financial_simulation": False, "production_contacted": False,
        "limitations": ["References cover retained evidence, not counterfactual paths or all historical checkpoints.",
                       "Absence of ownership/selection evidence is not proof of unreachability.",
                       "P02 adopted facts/models are not automatically admitted for another arm.",
                       "Native labels, eligibility and alias joins are not primary-source economic terms.",
                       "No payout/price, CVR valuation, identity upgrade, skipped trade or policy is selected.",
                       "This inventory cannot prove that no later unsupported action exists."]}
    save(out / "summary.json", summary)
    save(out / "request.json", config)
    save(out / "evidence-manifest.json", {f.name: {"bytes": f.stat().st_size, "sha256": file_hash(f)}
        for f in out.iterdir() if f.is_file() and f.name not in {"evidence-manifest.json", "source-scan-progress.json"}})
    print(json.dumps({k: summary[k] for k in ("status", "native_records", "unresolved_queue", "seconds")}), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(load(native(args.config)), args.output)


if __name__ == "__main__":
    main()
