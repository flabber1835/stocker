#!/usr/bin/env python3
"""Compare production compact champion with the independently frozen full replay."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REFERENCE_AST = "38143c63df9c92cbe28c55e39f753b084a6914f771f6aced2b69229bbefc4192"

if __name__ == "__main__":
    from tools.median5_equivalence import main
    main(profile="champion")
