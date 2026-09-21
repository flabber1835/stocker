"""Read retained canonical data without importing a historical strategy engine."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import itertools
import json
from decimal import Decimal
from pathlib import Path
import zipfile


BASE_ARCHIVE_SHA256 = "7d86c6f728f0392516dec5e2a709c16d45b2f46bc139fe7f3d29af25ae4dfce8"
BASE_DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
PREFIX_DATASET_SHA256 = "cf6dd784148b9d3eb2105459a038f482c64b1ab23e9966d4eb08da72a1b3de7a"
SFP_SOURCE = "PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_manifest(manifest, read_bytes):
    if manifest.get("status") != "PASS":
        raise ValueError("source reconstruction contains unresolved blockers")
    commitment = hashlib.sha256()
    for name, item in sorted(manifest["members"].items()):
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("source member path is not a basename")
        data = read_bytes(name)
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != item["bytes"] or digest != item["sha256"]:
            raise ValueError("source member bytes differ: " + name)
        commitment.update(f"{name}\0{digest}\0{len(data)}\n".encode())
    if commitment.hexdigest() != manifest["dataset_hash"]:
        raise ValueError("source dataset commitment differs")


def stitch_benchmark(prefix, base, bridge):
    if (not prefix or not base or prefix[-1]["session"] != "2005-12-30"
            or base[0]["session"] != "2006-01-03"):
        raise ValueError("benchmark partitions do not meet at the declared boundary")
    factor = Decimal(bridge)
    if not factor.is_finite() or factor <= 0:
        raise ValueError("invalid benchmark bridge factor")
    scale = Decimal(base[0]["level"]) / (Decimal(prefix[-1]["level"]) * factor)
    return [{**r, "level": str(Decimal(r["level"]) * scale)} for r in prefix] + base


class Inputs:
    def __init__(self, archive, prefix, sfp):
        if sha256(archive) != BASE_ARCHIVE_SHA256:
            raise ValueError("retained base archive identity differs")
        self.archive = zipfile.ZipFile(archive)
        names = self.archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member")
        matches = [n for n in names if n.endswith("/manifest.json") or n == "manifest.json"]
        if len(matches) != 1:
            raise ValueError("expected exactly one source manifest")
        self.base_root = matches[0].removesuffix("manifest.json")
        self.base = json.loads(self.archive.read(matches[0]))
        if self.base["dataset_hash"] != BASE_DATASET_SHA256:
            raise ValueError("retained base dataset identity differs")
        self.prefix_path = Path(prefix)
        self.prefix = json.loads((self.prefix_path / "manifest.json").read_text(encoding="utf-8"))
        if self.prefix["dataset_hash"] != PREFIX_DATASET_SHA256:
            raise ValueError("reconstructed warmup prefix identity differs")
        if (self.prefix["window"]["warmup_start"] != "2005-07-29"
                or self.prefix["window"]["end"] != "2005-12-30"):
            raise ValueError("warmup prefix window differs")
        validate_manifest(self.prefix, lambda n: (self.prefix_path / n).read_bytes())
        validate_manifest(self.base, lambda n: self.archive.read(self.base_root + n))
        source_hash = sha256(sfp)
        if any(m["source_files"][SFP_SOURCE]["sha256"] != source_hash
               for m in (self.base, self.prefix)):
            raise ValueError("benchmark bridge source differs from retained authorities")
        with gzip.open(sfp, "rt", encoding="utf-8", newline="") as stream:
            bridge = [r for r in csv.DictReader(stream)
                      if r["ticker"] == "SPY" and r["date"] == "2006-01-03"]
        if len(bridge) != 1:
            raise ValueError("benchmark bridge source is missing or duplicated")
        self.benchmark_bridge = {"source_sha256": source_hash, "row": bridge[0]}

    def benchmark(self):
        return stitch_benchmark(list(self.rows("benchmark.csv.gz", prefix=True)),
                                list(self.rows("benchmark.csv.gz")),
                                self.benchmark_bridge["row"]["close_to_close_factor"])

    def rows(self, member, *, prefix=False):
        binary = ((self.prefix_path / member).open("rb") if prefix
                  else self.archive.open(self.base_root + member))
        with binary:
            with gzip.GzipFile(fileobj=binary) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as text:
                    yield from csv.DictReader(text)

    def small_rows(self, member):
        yield from self.rows(member, prefix=True)
        yield from self.rows(member)

    def sessions(self):
        previous = None
        for year in range(2005, 2027):
            for day, rows in itertools.groupby(
                    self.rows(f"observations-{year}.csv.gz", prefix=year == 2005),
                    key=lambda r: r["session"]):
                if previous is not None and day <= previous:
                    raise ValueError("observation sessions duplicated or unordered")
                previous = day
                data = list(rows)
                ids = [r["security_id"] for r in data]
                if len(ids) != len(set(ids)):
                    raise ValueError("duplicate session security identity: " + day)
                yield day, data
