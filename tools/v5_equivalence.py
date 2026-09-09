#!/usr/bin/env python3
"""Compare the owner-selected Wealth Core V5 / EX3 V5 against pinned research."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.median5_equivalence import main

if __name__ == "__main__":
    main(profile="v5")
