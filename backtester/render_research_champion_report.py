#!/usr/bin/env python3
"""Render the retained Research Champion certification report as JSON + PDF."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _metric_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _pct(value):
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _num(value, digits=2):
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_pdf(path: Path, pages: list[list[str]]) -> None:
    objects: list[bytes] = []
    page_refs = []
    font_obj = 3
    for index in range(len(pages)):
        page_obj = 4 + index * 2
        content_obj = page_obj + 1
        page_refs.append(page_obj)
        lines = pages[index]
        stream_lines = ["BT", "/F1 9 Tf", "54 756 Td", "12 TL"]
        for line in lines:
            stream_lines.append(f"({_pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", "replace")
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
            f"/Contents {content_obj} 0 R >>"
        ).encode()
        content = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        while len(objects) < page_obj - 1:
            objects.append(b"")
        objects.append(page)
        objects.append(content)
    kids = " ".join(f"{obj} 0 R" for obj in page_refs)
    base = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, obj in enumerate(base):
        if i < len(objects):
            objects[i] = obj
        else:
            objects.append(obj)
    data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-root", type=Path, required=True)
    ap.add_argument("--certificate", type=Path, required=True)
    ap.add_argument("--output-pdf", type=Path, required=True)
    ap.add_argument("--output-json", type=Path, required=True)
    args = ap.parse_args()

    cert = _read_json(args.certificate)
    if cert.get("status") != "PIT_CERTIFIED":
        raise RuntimeError("report generation requires PIT_CERTIFIED certificate")
    summary = _read_json(args.replay_root / "summary.json")
    champion = _read_json(args.replay_root / "research-champion-identity.json")
    metrics = _metric_rows(args.replay_root / "metrics.csv")
    selected = [row for row in metrics if str(row.get("window_years")) in {"5", "10", "15", "20", "max"}]

    report = {
        "schema": "backtester.research-champion-final-report/1",
        "status": "PIT_CERTIFIED",
        "certificate_hash": cert.get("certificate_hash"),
        "source_identity": cert.get("source_identity"),
        "dataset_identity": cert.get("dataset_identity"),
        "configuration_identity": cert.get("configuration_identity"),
        "champion": champion,
        "metrics": selected,
        "replay_summary": {
            "status": summary.get("status"),
            "canonical_pit_dataset_hash": summary.get("canonical_pit_dataset_hash"),
            "candidate_session_security_type_coverage": summary.get("candidate_session_security_type_coverage"),
        },
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    cfg = (cert.get("configuration_identity") or {}).get("configuration") or {}
    params = cfg.get("parameters") or {}
    lines = [
        "RESEARCH CHAMPION - FORMAL PIT CERTIFICATION AND 20-YEAR BACKTEST",
        "",
        "Certification: PIT CERTIFIED",
        f"Certificate SHA256: {cert.get('certificate_hash','')}",
        f"Source SHA: {(cert.get('source_identity') or {}).get('source_sha','')}",
        f"Pinned runtime SHA: {params.get('runtime_main_sha','')}",
        f"Canonical dataset: {(cert.get('dataset_identity') or {}).get('dataset_id','')}",
        f"Dataset SHA256: {(cert.get('dataset_identity') or {}).get('dataset_sha256','')}",
        f"Window: {cfg.get('window',{}).get('measurement_start','')} through {cfg.get('window',{}).get('end','')}",
        "",
        f"Champion profile: {champion.get('profile','')}",
        f"Champion profile SHA256: {champion.get('profile_sha256','')}",
        f"LDRC_REC: {params.get('LDRC_REC')}",
        f"LDRC_R20: {params.get('LDRC_R20')}",
        f"LDRC_V: {params.get('LDRC_V')}",
        f"LDRC_DD: {params.get('LDRC_DD')}",
        f"divergence_spy_floor: {params.get('divergence_spy_floor')}",
        f"full_recovery_r40_floor: {params.get('full_recovery_r40_floor')}",
        f"FAST_damaged: {params.get('FAST_damaged')}",
        f"healthy_damaged_ceiling: {params.get('healthy_damaged_ceiling')}",
        "",
        "BACKTEST METRICS",
        "Window  Variant      CAGR       Max DD     Sharpe    Ending Multiple",
    ]
    for row in selected:
        lines.append(
            f"{str(row.get('window_years','')):>6}  {str(row.get('variant','')):<10}  "
            f"{_pct(row.get('cagr')):>9}  {_pct(row.get('max_drawdown')):>9}  "
            f"{_num(row.get('sharpe')):>7}  {_num(row.get('ending_multiple')):>15}"
        )
    coverage = summary.get("candidate_session_security_type_coverage") or {}
    lines.extend([
        "",
        "CERTIFICATION EVIDENCE",
        f"Candidate observations: {coverage.get('base_candidates','N/A')}",
        f"Unknown candidate classifications: {coverage.get('unknown_classifications','N/A')}",
        "Unknown corpus security types are admitted only as explicit fail-closed ineligible rows.",
        "Incomplete terminal terms are retained as explicit fail-closed terminal ledger events.",
        "Held-terminal accounting, resolved NAV, causality, and future-leak checks passed.",
        "",
        "This certificate covers the defined PIT/causality/universe/execution contract for this exact replay.",
    ])
    pages = [lines[i:i+54] for i in range(0, len(lines), 54)] or [["Research Champion report"]]
    _write_pdf(args.output_pdf, pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
