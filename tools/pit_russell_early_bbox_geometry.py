#!/usr/bin/env python3
"""Measure early Russell PDF bbox geometry without accepting membership rows.

Research only. Raw PDF and full bbox XML remain ephemeral. Persisted output contains
coordinate histograms and a tiny structural sample sufficient to define a deterministic
column parser. The PDF may be supplied locally so the geometry stage can reuse bytes
already fetched by a preceding diagnostic step.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Sequence
import xml.etree.ElementTree as ET

import pit_russell_archive_probe as archive
from pit_russell_pdf_membership_extract import is_ticker, normalize, query_exact_capture


def tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def bbox_xml(payload: bytes) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext unavailable")
    with tempfile.TemporaryDirectory(prefix="russell-early-geom-") as tmp:
        pdf = Path(tmp) / "source.pdf"
        out = Path(tmp) / "bbox.xml"
        pdf.write_bytes(payload)
        proc = subprocess.run([exe, "-bbox-layout", str(pdf), str(out)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode:
            raise RuntimeError(f"pdftotext bbox rc={proc.returncode}: {proc.stderr[:400]}")
        return out.read_text(errors="replace")


def rounded(value: float, step: float = 5.0) -> float:
    return round(value / step) * step


def geometry(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    ticker_x = Counter()
    all_x = Counter()
    row_word_counts = Counter()
    page_widths = []
    samples = []

    for page_no, page in enumerate((x for x in root.iter() if tag_name(x.tag) == "page"), start=1):
        try:
            page_widths.append(float(page.attrib.get("width", "0")))
        except ValueError:
            pass
        rows = []
        for line in (x for x in page.iter() if tag_name(x.tag) == "line"):
            words = []
            for word in (x for x in line.iter() if tag_name(x.tag) == "word"):
                text = normalize("".join(word.itertext()))
                if not text:
                    continue
                x = float(word.attrib.get("xMin", line.attrib.get("xMin", "0")))
                y = float(word.attrib.get("yMin", line.attrib.get("yMin", "0")))
                words.append((x, y, text))
                all_x[rounded(x)] += 1
                if is_ticker(text.upper()):
                    ticker_x[rounded(x)] += 1
            if words:
                rows.append(sorted(words))

        row_word_counts.update(len(row) for row in rows)
        if len(samples) < 12:
            for row in rows:
                if len(samples) >= 12:
                    break
                ticker_like = sum(1 for _, _, text in row if is_ticker(text.upper()))
                if ticker_like >= 2 and len(row) >= 4:
                    samples.append({
                        "page": page_no,
                        "word_count": len(row),
                        "ticker_like_count": ticker_like,
                        "words": [
                            {"x": round(x, 2), "chars": len(text), "ticker_like": is_ticker(text.upper())}
                            for x, _, text in row[:20]
                        ],
                    })

    return {
        "page_count": len(page_widths),
        "page_widths": sorted({round(x, 2) for x in page_widths}),
        "ticker_x_clusters_top": [{"x": x, "count": c} for x, c in ticker_x.most_common(30)],
        "all_x_clusters_top": [{"x": x, "count": c} for x, c in all_x.most_common(30)],
        "row_word_count_histogram": dict(sorted(row_word_counts.items())),
        "structural_samples": samples,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf-file", type=Path, default=None, help="Ephemeral local PDF fetched by a preceding step")
    p.add_argument("--url", default=None)
    p.add_argument("--timestamp", default=None)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--attempts", type=int, default=5)
    args = p.parse_args(argv)
    if args.pdf_file is None and (not args.url or not args.timestamp):
        p.error("provide --pdf-file or both --url and --timestamp")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cap = None
    final_url = None
    if args.pdf_file is not None:
        payload = args.pdf_file.read_bytes()
        if not payload.startswith(b"%PDF-"):
            raise RuntimeError(f"local file is not a PDF: {args.pdf_file}")
    else:
        cap = query_exact_capture(args.url, args.timestamp, args.timeout, args.attempts)
        payload, status, content_type, final_url = archive._request(cap.raw_archive_url, timeout=args.timeout, attempts=args.attempts)
        if status != 200 or not payload.startswith(b"%PDF-"):
            raise RuntimeError(f"not PDF status={status} content_type={content_type!r}")

    xml_text = bbox_xml(payload)
    result = {
        "schema": 2,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "capture": asdict(cap) if cap is not None else {"timestamp": args.timestamp, "original": args.url},
        "fetch_final_url": final_url,
        "pdf_sha256": hashlib.sha256(payload).hexdigest(),
        "bbox_sha256": hashlib.sha256(xml_text.encode()).hexdigest(),
        "source_mode": "local-ephemeral-pdf" if args.pdf_file is not None else "direct-wayback-fetch",
        "raw_pdf_persisted": False,
        "full_bbox_persisted": False,
        "accepted_as_corpus": False,
        "geometry": geometry(xml_text),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "geometry.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    g = result["geometry"]
    lines = [
        "# Early Russell bbox geometry",
        "",
        "Diagnostic only; no membership rows are accepted.",
        "",
        f"- Capture: `{args.timestamp or (cap.timestamp if cap else 'local')}`",
        f"- PDF SHA-256: `{result['pdf_sha256']}`",
        f"- Source mode: `{result['source_mode']}`",
        f"- Pages: **{g['page_count']}**",
        f"- Page widths: `{g['page_widths']}`",
        "",
        "## Strongest ticker-like x clusters",
        "",
    ]
    lines += [f"- x={item['x']:.1f}: {item['count']}" for item in g["ticker_x_clusters_top"][:12]]
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"pages": g["page_count"], "ticker_x_top": g["ticker_x_clusters_top"][:8]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
