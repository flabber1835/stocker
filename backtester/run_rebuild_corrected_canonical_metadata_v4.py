#!/usr/bin/env python3
"""Run the issuer-safe V4 corrected canonical observation audit.

Compatibility bridge: the V4 audit expects a package-verification callable while
historical_metadata_reconstruction_v2 exposes the same checksum contract as
verify_checksums(). Keep the immutable V2 module unchanged and bind that contract
at the runner boundary.
"""
from backtester import historical_metadata_reconstruction_v2 as v2

v2.verify_package = v2.verify_checksums

from backtester import rebuild_corrected_canonical_metadata_v4 as audit


if __name__ == "__main__":
    raise SystemExit(audit.main())
