from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SeedLedger:
    generator_version: str
    seed: int

    def seed_for(self, stream_name: str) -> int:
        material = f"{self.generator_version}|{self.seed}|{stream_name}".encode("utf-8")
        digest = hashlib.sha256(material).digest()
        return int.from_bytes(digest[:16], "big", signed=False)

    def generator(self, stream_name: str) -> np.random.Generator:
        return np.random.Generator(np.random.PCG64DXSM(self.seed_for(stream_name)))

    def describe(self, stream_names: list[str]) -> dict[str, str]:
        return {name: f"0x{self.seed_for(name):032x}" for name in sorted(stream_names)}
