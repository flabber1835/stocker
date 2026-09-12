from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from pathlib import Path


def _rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


@dataclass(frozen=True)
class SyntheticPITWorld:
    """Point-in-time reader over the strategy-visible public namespace only."""

    public_dir: Path

    def __post_init__(self) -> None:
        public_dir = Path(self.public_dir)
        object.__setattr__(self, "public_dir", public_dir)
        if public_dir.name != "public":
            raise ValueError("SyntheticPITWorld requires the generated public/ directory")
        required = ("prices.csv.gz", "disclosures.csv.gz", "actions.csv.gz", "security_master.csv.gz", "universe.csv.gz")
        missing = [name for name in required if not (public_dir / name).is_file()]
        if missing:
            raise FileNotFoundError(f"missing synthetic public tables: {missing}")

    def prices_through(self, as_of: str) -> list[dict[str, str]]:
        return [row for row in _rows(self.public_dir / "prices.csv.gz") if row["date"] <= as_of]

    def universe_as_of(self, as_of: str) -> list[dict[str, str]]:
        return [row for row in _rows(self.public_dir / "universe.csv.gz") if row["snapshot_date"] == as_of]

    def actions_known_as_of(self, as_of: str) -> list[dict[str, str]]:
        return [row for row in _rows(self.public_dir / "actions.csv.gz") if row["announced_at"] <= as_of]

    def fundamentals_as_of(self, as_of: str) -> list[dict[str, str]]:
        """Latest publicly filed version per company/period visible at ``as_of``."""
        latest: dict[tuple[str, str], dict[str, str]] = {}
        for row in _rows(self.public_dir / "disclosures.csv.gz"):
            if row["filed_at"] > as_of:
                continue
            key = (row["company_id"], row["period_end"])
            current = latest.get(key)
            if current is None or (row["filed_at"], int(row["version"])) > (current["filed_at"], int(current["version"])):
                latest[key] = row
        return [latest[key] for key in sorted(latest)]
