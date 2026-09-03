#!/usr/bin/env python3
"""Merge frozen V4 external SEC shards and extend the ownership-strict candidate corpus.

External discovery remains candidate-only. This module authenticates every frozen source,
requires strict-prior evidence, normalizes only exact SEC ticker proofs, and preserves the
existing ownership-strict admission contract for the downstream canonical observation audit.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

EXTERNAL_PLAN_SCHEMA = "backtester.historical-metadata-external-plan-v4/1"
EXTERNAL_EVIDENCE_SCHEMA = "backtester.historical-metadata-authority-expansion-v4.issuer-safe/1"
EXTERNAL_MERGE_SCHEMA = "backtester.historical-metadata-authority-expansion-v4.external-merge/1"
OWNERSHIP_STRICT_MERGE_SCHEMA = "backtester.historical-metadata-reconstruction-v4.ownership-strict-candidate-merge/1"
OWNERSHIP_FORMS = {"3", "3/A", "4", "4/A", "5", "5/A"}
CURRENT_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A", "8-K", "8-K/A", "S-1", "S-1/A", "F-1", "F-1/A", "10", "10/A"}
EXTENDED_FORMS = {"6-K", "6-K/A", "S-3", "S-3/A", "F-3", "F-3/A", "S-4", "S-4/A", "F-4", "F-4/A", "424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8", "POS AM"}
REGISTRATION_FORMS = {"8-A12B", "8-A12B/A", "8-A12G", "8-A12G/A"}
IDENTITY_AUTHORITY_FORMS = CURRENT_FORMS | EXTENDED_FORMS | OWNERSHIP_FORMS | REGISTRATION_FORMS
FIELDS = [
    "shard", "security_id", "ticker", "first_session", "last_session", "resolution_route",
    "candidate_cik", "cik_authority", "source_cik", "source_cik_target_relation",
    "issuer_cik_source", "issuer_cik_matches_source", "candidate_kind", "candidate_quality",
    "form", "filed", "accession", "classification", "sic", "evidence_excerpt", "source_url",
    "source_sha256", "artifact_member", "admission_effect",
]
EXTERNAL_EVIDENCE_FIELDS = [
    "security_id", "ticker", "bucket", "authority_before", "candidate_cik", "accession", "form",
    "filed", "identity_proof_kind", "identity_proof_excerpt", "classification",
    "classification_excerpt", "sic", "form_authority", "source_url", "source_sha256",
    "source_member", "discovery_url", "discovery_sha256", "admission_effect", "source_cik",
    "issuer_cik_source", "issuer_cik_matches_source",
]
PLAN_FIELDS = [
    "security_id", "ticker", "first_session", "last_session", "bucket", "type_unresolved",
    "sector_unresolved", "issuer_unresolved", "authority_before", "search_start", "search_end",
    "impact", "issuer_resolved", "issuer_state", "source_inventory_sha256",
]
RESULT_FIELDS = [
    "security_id", "ticker", "authority_before", "discovery_hits", "display_name_exact_hits",
    "candidate_accessions", "filings_fetched", "admissible_identity_ciks", "candidate_rows",
    "status", "reason",
]
MANIFEST_FIELDS = [
    "security_id", "ticker", "role", "url", "status", "sha256", "bytes", "retrieved_at",
    "artifact_member",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_gz(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv_gz(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer=csv.DictWriter(text,fieldnames=list(fields),extrasaction="ignore",lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def verify_checksums(root: Path) -> None:
    manifest=root/"SHA256SUMS.txt"
    if not manifest.is_file():
        raise RuntimeError(f"missing checksum manifest: {root}")
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name=line.split(None,1)
        path=root/name.strip()
        if not path.is_file() or sha256_file(path)!=digest:
            raise RuntimeError(f"checksum mismatch: {path}")


def write_checksums(root: Path, *, include_sources: bool = False) -> None:
    files=[]
    for path in root.rglob("*"):
        if not path.is_file() or path.name=="SHA256SUMS.txt":
            continue
        rel=path.relative_to(root).as_posix()
        if not include_sources and rel.startswith("sources/"):
            continue
        files.append(path)
    lines=[f"{sha256_file(path)}  {path.relative_to(root).as_posix()}" for path in sorted(files)]
    (root/"SHA256SUMS.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")


def _copy_sources(source_root: Path, output: Path) -> int:
    count=0
    root=source_root/"sources"
    if not root.is_dir():
        return 0
    for source in root.rglob("*.bin"):
        rel=source.relative_to(source_root)
        dest=output/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if sha256_file(dest)!=sha256_file(source):
                raise RuntimeError(f"content-address source collision: {rel}")
        else:
            shutil.copyfile(source,dest)
            count += 1
    return count


def _shard_root(inputs: Path, name: str) -> Path:
    for candidate in (inputs / name, inputs / "backtester-results" / name):
        if candidate.is_dir():
            return candidate
    return inputs / name


def merge_external(inputs: Path, output: Path, *, expected_shards: int, expected_cohort: int,
                   source_run_id: str, source_sha: str) -> dict[str, object]:
    plans=[]; evidence=[]; results=[]; manifests=[]
    plan_ids=set(); result_ids=set(); source_index={}
    candidate_status=Counter(); transport=Counter(); copied=0
    inventory_sha=""
    for shard in range(expected_shards):
        plan_root=inputs/f"backtester-results/v4-external-sec-plan-{shard}"
        evidence_root=inputs/f"backtester-results/v4-external-sec-evidence-{shard}"
        if not plan_root.is_dir() or not evidence_root.is_dir():
            raise RuntimeError(f"missing external shard {shard}")
        verify_checksums(plan_root); verify_checksums(evidence_root)
        ps=json.loads((plan_root/"plan_summary.json").read_text())
        es=json.loads((evidence_root/"summary.json").read_text())
        if ps.get("schema")!=EXTERNAL_PLAN_SCHEMA or ps.get("status")!="PASS":
            raise RuntimeError(f"invalid external plan shard {shard}")
        if ps.get("identity_scope")!="known-or-partial" or int(ps.get("shard_index",-1))!=shard or int(ps.get("shard_count",-1))!=expected_shards:
            raise RuntimeError(f"external plan identity/shard mismatch {shard}")
        if int(ps.get("cohort_rows",-1))!=expected_cohort:
            raise RuntimeError(f"external cohort mismatch {shard}")
        inventory_sha = inventory_sha or str(ps.get("source_inventory_sha256") or "")
        if str(ps.get("source_inventory_sha256") or "") != inventory_sha:
            raise RuntimeError("external shards do not share one authoritative residual")
        if es.get("schema")!=EXTERNAL_EVIDENCE_SCHEMA or es.get("status")!="PASS" or es.get("candidate_only") is not True:
            raise RuntimeError(f"invalid external evidence shard {shard}")
        if int(es.get("episodes",-1))!=int(ps.get("planned_rows",-2)):
            raise RuntimeError(f"plan/evidence episode mismatch {shard}")
        shard_plans=read_csv_gz(plan_root/"plan.csv.gz")
        shard_results=read_csv_gz(evidence_root/"episode_results.csv.gz")
        shard_evidence=read_csv_gz(evidence_root/"candidate_evidence.csv.gz")
        shard_manifest=read_csv_gz(evidence_root/"source_manifest.csv.gz")
        if len(shard_plans)!=int(ps["planned_rows"]) or len(shard_results)!=len(shard_plans):
            raise RuntimeError(f"row count mismatch shard {shard}")
        pids={row["security_id"] for row in shard_plans}; rids={row["security_id"] for row in shard_results}
        if pids!=rids or plan_ids & pids:
            raise RuntimeError(f"overlap/result coverage failure shard {shard}")
        plan_ids |= pids; result_ids |= rids
        by_sid={row["security_id"]:row for row in shard_plans}
        for row in shard_evidence:
            plan=by_sid.get(row.get("security_id", ""))
            if not plan:
                raise RuntimeError("external candidate targets episode outside shard plan")
            if row.get("admission_effect")!="NONE_CANDIDATE_ONLY":
                raise RuntimeError("external evidence has prior admission effect")
            if not row.get("filed") or row["filed"] >= plan["authority_before"]:
                raise RuntimeError("external evidence violates strict-prior boundary")
            member=row.get("source_member", ""); source_path=evidence_root/member
            if not member or not source_path.is_file() or sha256_file(source_path)!=row.get("source_sha256"):
                raise RuntimeError("external candidate raw filing is missing or hash-mismatched")
        for row in shard_manifest:
            if row.get("status")!="200" or not row.get("artifact_member"):
                continue
            path=evidence_root/row["artifact_member"]
            if not path.is_file() or sha256_file(path)!=row.get("sha256"):
                raise RuntimeError("external source manifest raw object mismatch")
            key=(row.get("url",""),row.get("sha256",""))
            source_index[key]=row
        copied += _copy_sources(evidence_root,output)
        plans.extend(shard_plans); evidence.extend(shard_evidence); results.extend(shard_results); manifests.extend(shard_manifest)
        candidate_status.update({
            "candidate_found":int(es.get("candidate_found",0)),"ambiguous":int(es.get("ambiguous",0)),
            "no_discovery_match":int(es.get("no_discovery_match",0)),"no_archived_proof":int(es.get("no_archived_proof",0)),
        })
        transport.update({k:int(v) for k,v in (es.get("transport") or {}).items() if isinstance(v,(int,float))})
    if len(plan_ids)!=expected_cohort or result_ids!=plan_ids:
        raise RuntimeError(f"external merged coverage mismatch: {len(plan_ids)} != {expected_cohort}")
    plans.sort(key=lambda r:(r["ticker"],r["security_id"])); results.sort(key=lambda r:(r["ticker"],r["security_id"]))
    evidence.sort(key=lambda r:(r["ticker"],r["security_id"],r["filed"],r["candidate_cik"],r["accession"],r["source_sha256"]))
    manifests.sort(key=lambda r:(r["ticker"],r["security_id"],r["role"],r["url"],r["sha256"]))
    output.mkdir(parents=True,exist_ok=True)
    write_csv_gz(output/"plan.csv.gz",PLAN_FIELDS,plans); write_csv_gz(output/"candidate_evidence.csv.gz",EXTERNAL_EVIDENCE_FIELDS,evidence)
    write_csv_gz(output/"episode_results.csv.gz",RESULT_FIELDS,results); write_csv_gz(output/"source_manifest.csv.gz",MANIFEST_FIELDS,manifests)
    summary={
        "schema":EXTERNAL_MERGE_SCHEMA,"status":"PASS","candidate_only":True,
        "admission_effect":"NONE","canonical_price_dataset_rewritten":False,
        "unknown_never_means_ineligible":True,"discovery_is_authority":False,
        "strict_prior_rule":"filing_date < earliest unresolved canonical observation",
        "source_run_id":str(source_run_id),"source_sha":str(source_sha),"merged_shards":expected_shards,
        "episodes":len(plan_ids),"candidate_evidence_rows":len(evidence),"source_manifest_rows":len(manifests),
        "unique_frozen_source_objects":len(source_index),"new_source_files_copied":copied,
        "source_inventory_sha256":inventory_sha,"episode_status":dict(candidate_status),"transport":dict(transport),
        "next_gate":"combine with ownership-strict retained candidates; then run full canonical observation audit",
    }
    (output/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    write_checksums(output, include_sources=True)
    return summary


def _normalized_identity_quality(form: str, proof: str) -> str:
    form=form.upper(); proof=proof.strip()
    if form not in IDENTITY_AUTHORITY_FORMS:
        return ""
    if form in OWNERSHIP_FORMS:
        return "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML" if proof=="SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML" else ""
    if proof=="SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML":
        return proof
    if proof in {"SEC_EXPLICIT_TRADING_SYMBOL_LABEL","SEC_EXCHANGE_QUALIFIED_TICKER","SEC_REGISTRATION_FORM_TRADING_SYMBOL"}:
        return "SEC_EXPLICIT_TRADING_SYMBOL_LABEL"
    return ""


def _type_quality(form: str) -> str:
    form=form.upper()
    if form in CURRENT_FORMS or form in REGISTRATION_FORMS: return "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"
    if form in EXTENDED_FORMS: return "EXTENDED_FORM_EXACT_TICKER_CLASS_CANDIDATE"
    if form in OWNERSHIP_FORMS: return "OWNERSHIP_FORM_SUPPLEMENTARY_CLASS_ONLY"
    return "OTHER_FORM_EXACT_TICKER_CLASS_CANDIDATE"


def combine(retained_root: Path, external_root: Path, output: Path, *, expected_retained_sha256: str) -> dict[str, object]:
    retained_summary=json.loads((retained_root/"summary.json").read_text())
    external_summary=json.loads((external_root/"summary.json").read_text())
    retained_path=retained_root/"candidate_evidence.csv.gz"
    if retained_summary.get("schema")!=OWNERSHIP_STRICT_MERGE_SCHEMA or retained_summary.get("status")!="PASS" or retained_summary.get("candidate_only") is not True or int(retained_summary.get("merged_shards",-1))!=32:
        raise RuntimeError("retained ownership-strict candidate corpus is invalid")
    retained_sha=sha256_file(retained_path)
    if expected_retained_sha256 and retained_sha!=expected_retained_sha256:
        raise RuntimeError("retained ownership-strict candidate corpus hash mismatch")
    if external_summary.get("schema")!=EXTERNAL_MERGE_SCHEMA or external_summary.get("status")!="PASS" or external_summary.get("candidate_only") is not True:
        raise RuntimeError("external SEC merged evidence is invalid")
    plans={row["security_id"]:row for row in read_csv_gz(external_root/"plan.csv.gz")}
    external_rows=read_csv_gz(external_root/"candidate_evidence.csv.gz")
    transformed=[]; transform_counts=Counter()
    for row in external_rows:
        plan=plans.get(row.get("security_id", ""))
        if not plan: raise RuntimeError("external candidate lacks merged plan episode")
        form=str(row.get("form") or "").upper()
        quality=_normalized_identity_quality(form,str(row.get("identity_proof_kind") or ""))
        if not quality:
            transform_counts["evidence_without_ownership_strict_identity_proof"] += 1
            continue
        base={
            "shard":"external-sec","security_id":row["security_id"],"ticker":row["ticker"],
            "first_session":plan["first_session"],"last_session":plan["last_session"],
            "resolution_route":"EXTERNAL_SEC_STRICT_PRIOR","candidate_cik":row.get("candidate_cik", ""),
            "cik_authority":"DISCOVERY_ONLY_HINT","source_cik":row.get("source_cik", ""),
            "source_cik_target_relation":"EXTERNAL_EFTS_DISCOVERY",
            "issuer_cik_source":row.get("issuer_cik_source", ""),
            "issuer_cik_matches_source":row.get("issuer_cik_matches_source", ""),
            "form":form,"filed":row.get("filed", ""),"accession":row.get("accession", ""),
            "source_url":row.get("source_url", ""),"source_sha256":row.get("source_sha256", ""),
            "artifact_member":row.get("source_member", ""),"admission_effect":"NONE_CANDIDATE_ONLY",
        }
        transformed.append(base | {
            "candidate_kind":"IDENTITY_EXACT_TICKER","candidate_quality":quality,"classification":"","sic":"",
            "evidence_excerpt":f"{row.get('identity_proof_kind','')}: {row.get('identity_proof_excerpt','')}",
        })
        transform_counts["identity_candidates"] += 1
        classification=str(row.get("classification") or "")
        if classification in {"common","non_common"}:
            transformed.append(base | {
                "candidate_kind":"SECURITY_TYPE_EXACT_TICKER_CLASS","candidate_quality":_type_quality(form),
                "classification":classification,"sic":"","evidence_excerpt":row.get("classification_excerpt", ""),
            })
            transform_counts["security_type_candidates"] += 1
        sic="".join(ch for ch in str(row.get("sic") or "") if ch.isdigit())
        if 3 <= len(sic) <= 4:
            sic=sic.zfill(4)
            transformed.append(base | {
                "candidate_kind":"SIC_HEADER","candidate_quality":"HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP",
                "classification":"","sic":sic,"evidence_excerpt":f"STANDARD INDUSTRIAL CLASSIFICATION [{sic}]",
            })
            transform_counts["sic_candidates"] += 1
    retained=read_csv_gz(retained_path)
    key_fields=("security_id","candidate_cik","candidate_kind","candidate_quality","form","filed","accession","classification","sic","source_sha256")
    chosen={}
    for row in sorted(retained+transformed,key=lambda r:(r.get("source_url",""),r.get("artifact_member",""))):
        key=tuple(str(row.get(field,"")) for field in key_fields)
        chosen.setdefault(key,row)
    combined=[chosen[key] for key in sorted(chosen)]
    output.mkdir(parents=True,exist_ok=True)
    write_csv_gz(output/"candidate_evidence.csv.gz",FIELDS,combined)
    by_kind=Counter(row.get("candidate_kind","") for row in combined)
    by_quality=Counter(row.get("candidate_quality","") for row in combined)
    episodes_by_kind=defaultdict(set)
    for row in combined: episodes_by_kind[row.get("candidate_kind","")].add(row.get("security_id",""))
    ownership_identity=[row for row in combined if row.get("candidate_kind")=="IDENTITY_EXACT_TICKER" and row.get("form") in OWNERSHIP_FORMS]
    if any(row.get("candidate_quality")!="SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML" for row in ownership_identity):
        raise RuntimeError("combined corpus violates ownership-strict identity proof")
    summary={
        "schema":OWNERSHIP_STRICT_MERGE_SCHEMA,"status":"PASS","candidate_only":True,"admission_effect":"NONE",
        "merged_shards":32,"candidate_rows":len(combined),"retained_candidate_rows":len(retained),
        "retained_candidate_sha256":retained_sha,"external_authority_extension":True,
        "external_authority_shards":external_summary["merged_shards"],"external_authority_episodes":external_summary["episodes"],
        "external_evidence_rows":len(external_rows),"external_transformed_candidate_rows":len(transformed),
        "external_source_run_id":external_summary["source_run_id"],"external_source_sha":external_summary["source_sha"],
        "external_source_inventory_sha256":external_summary["source_inventory_sha256"],
        "candidate_counts_by_kind":dict(by_kind),"candidate_counts_by_quality":dict(by_quality),
        "episodes_with_identity_candidates":len(episodes_by_kind.get("IDENTITY_EXACT_TICKER",set())),
        "episodes_with_security_type_candidates":len(episodes_by_kind.get("SECURITY_TYPE_EXACT_TICKER_CLASS",set())),
        "episodes_with_sic_candidates":len(episodes_by_kind.get("SIC_HEADER",set())),
        "ownership_identity_candidates":len(ownership_identity),
        "ownership_identity_source_cik_mismatches":sum(row.get("issuer_cik_matches_source")=="false" for row in ownership_identity),
        "external_transform_counts":dict(transform_counts),
        "next_gate":"ownership-strict authority allocation and 31.8M-row strict-prior canonical observation audit",
    }
    (output/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    write_checksums(output)
    return summary


def main(argv: Sequence[str] | None=None) -> int:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("merge-external"); p.add_argument("--inputs",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--expected-shards",type=int,default=8); p.add_argument("--expected-cohort",type=int,default=4037); p.add_argument("--source-run-id",required=True); p.add_argument("--source-sha",required=True)
    p=sub.add_parser("combine"); p.add_argument("--retained-root",type=Path,required=True); p.add_argument("--external-root",type=Path,required=True); p.add_argument("--output",type=Path,required=True); p.add_argument("--expected-retained-sha256",default="")
    args=parser.parse_args(argv)
    if args.cmd=="merge-external": result=merge_external(args.inputs,args.output,expected_shards=args.expected_shards,expected_cohort=args.expected_cohort,source_run_id=args.source_run_id,source_sha=args.source_sha)
    else: result=combine(args.retained_root,args.external_root,args.output,expected_retained_sha256=args.expected_retained_sha256)
    print(json.dumps(result,indent=2,sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
